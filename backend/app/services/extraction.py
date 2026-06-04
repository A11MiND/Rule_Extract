from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..runtime_config import clamp_concurrency
from ..schemas import RuleBase
from .artifacts import document_storage_dir
from .llm import LLMClient


DEFAULT_EXTRACT_SYSTEM_PROMPT = """You extract structured rules from NEC public works Practice Notes.
Return JSON only: {"rules": [...]}. Each rule must include source, subject, condition,
action, type, actor, target, deadline, options, dependencies, next_rule_ids, confidence,
review_status, notes. review_status must be "draft".

─── TYPE CLASSIFICATION (apply in this order) ───

1. PROHIBITION — text says something must NOT be done.
   Keywords: "shall not", "must not", "is prohibited", "is not allowed",
   "may not", "no person shall", "not be permitted".
   NEC example: "The Contractor shall not sub-let the whole of the works."

2. PERMISSION — text grants discretion or exemption.
   Keywords: "may" (when granting choice), "at the discretion of",
   "is permitted to", "may at its option", "unless otherwise agreed",
   "the Project Manager may waive".
   NEC example: "The Contractor may submit a revised programme."

3. DEADLINE — text sets a time limit, due date, or response window.
   Keywords: "within X weeks/days", "no later than", "by [date]",
   "the period for reply is", "before the deadline", "time limit",
   "shall respond within", "within the period of".
   NEC example: "The Project Manager shall reply within 2 weeks."

4. OPTION — text describes alternative branches or elective contract clauses.
   Keywords: "Option A/B/C/D/E/F/G", "Option X1/X2/...", "secondary option",
   "the Employer may choose", "either ... or ...", "alternative",
   "Options", "choice of", "elects to use".
   NEC example: "Under Option C, the Contractor's share is calculated..."

5. DEFINITION — text defines a term or concept.
   Keywords: "means", "is defined as", "refers to", "includes",
   "the term ... shall mean", "are defined in", "defines".
   NEC example: ""Defined Cost" means the cost of components in the
   Schedule of Cost Components."

6. PROCEDURE — text describes a process, workflow, or sequence of steps.
   Keywords: "first ... then", "steps", "procedure for", "shall be
   followed", "the process is", "shall be carried out in accordance",
   sequential actions (first/second/third), "flowchart".
   NEC example: "The Project Manager assesses the amount due, then
   certifies payment within 7 days."

7. CHECKLIST — text enumerates items to verify, submit, or complete.
   Keywords: "checklist", "shall include", "shall contain the following",
   "the following items", "comprising of", bullet/numbered lists of
   deliverables, "tender submission shall include", "documents required".
   NEC example: "The tender submission shall include: (a) Form of Tender,
   (b) priced Bill of Quantities..."

8. OBLIGATION — text imposes a mandatory duty or requirement.
   Keywords: "shall", "must", "is required to", "is to", "has a duty to",
   "the Employer/Contractor/Project Manager shall", "shall ensure",
   "is responsible for", "will be".
   NEC example: "The Contractor shall provide the works in accordance
   with the Scope."

9. BACKGROUND — text that is purely informational, historical, or
   explanatory with no actionable requirement.
   Use this for: history sections, introductory context, descriptions of
   existing practices, summaries of legislation, explanations of "why"
   rather than "what must be done".
   NEC example: "In 2000, the Government set up the Construction Industry
   Review Committee..."

─── WHEN TO SKIP ───

Do NOT extract rules from sections that are:
- Pure navigation (table of contents, section headers only)
- Empty or whitespace-only
- Pure background/history with zero actionable content → use "background"

─── CONFIDENCE ───

Score 0.85-1.0: text explicitly states the rule with clear subject/condition/action.
Score 0.65-0.85: rule is reasonably inferred but wording is indirect.
Score 0.45-0.65: significant inference needed; multiple interpretations possible.
Score <0.45: speculative — consider whether this should be a rule at all.

─── FORMAT ───

- subject: one-line summary of what the rule requires (max 120 chars).
- condition: when/under what circumstances the rule applies. Use "" if unconditional.
- action: what must (or must not) be done. Be specific and self-contained.
- actor: who performs the action (e.g. "Project Manager", "Contractor"). "" if unclear.
- target: who/what the action applies to. "" if same as actor.
- deadline: time constraint if any. "" if none.
- options: [] unless the rule describes alternative branches (Option A/B/C).
- For option branches, populate options[].{label, condition, action, next_rule_ids}.
"""

EXTRACTION_BATCH_SIZE = 5
WINDOW_BATCH_SIZE = 5
VALID_RULE_TYPES = {
    "obligation",
    "prohibition",
    "permission",
    "definition",
    "procedure",
    "deadline",
    "option",
    "checklist",
    "background",
}
TYPE_ALIASES = {
    "procedural": "procedure",
    "process": "procedure",
    "requirement": "obligation",
    "required": "obligation",
    "mandatory": "obligation",
}


def extract_rules(
    db: Session,
    document: models.Document,
    llm: LLMClient,
    concurrency: int = 8,
    system_prompt: str = "",
) -> int:
    """Sliding-window extraction: group by chapter, batch sections within each chapter.

    Chapters provide shared context (heading, cross-refs, definitions). Sections are
    batched in groups of WINDOW_BATCH_SIZE so the LLM thoroughly processes each section."""
    grouping_level = int(getattr(document, "grouping_level", 2) or 2)

    sections = list(document.sections)
    windows = split_document_by_level(sections, grouping_level)
    if not windows:
        document.status = "rules_extracted"
        db.commit()
        return 0

    cross_ref_map = build_cross_reference_map(sections)
    all_sections_by_id = {s.id: s for s in sections}
    definitions = gather_definitions(sections)

    # Flatten all (window, batch) pairs into a single job list
    jobs: list[tuple[int, str, list[dict[str, Any]], str, list[models.Section]]] = []
    for window in windows:
        chapter_context = build_chapter_context(
            window, definitions, cross_ref_map, all_sections_by_id, document.id,
        )
        batches = chunked(window.sections, WINDOW_BATCH_SIZE)
        for batch in batches:
            jobs.append((len(jobs) + 1, window.title, [section_snapshot(section) for section in batch], chapter_context, batch))

    total_batches = len(jobs)
    manifest = dict(document.artifact_manifest or {})
    manifest["llm_windows_total"] = total_batches
    manifest["llm_windows_completed"] = 0
    manifest["llm_window_failures"] = 0
    manifest["llm_windows_path"] = str(llm_windows_path(document.id))
    document.artifact_manifest = manifest

    prompt = system_prompt or DEFAULT_EXTRACT_SYSTEM_PROMPT
    max_workers = clamp_concurrency(concurrency)

    saved_count = 0
    seen_ids: set[str] = set()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                extract_rules_from_batch,
                llm, prompt, window_title, snapshots, chapter_context, idx,
            ): idx
            for idx, window_title, snapshots, chapter_context, _batch in jobs
        }
        for future in as_completed(futures):
            idx = futures[future]
            _, window_title, _, _, batch = jobs[idx - 1]
            section_by_id = {s.id: s for s in batch}
            try:
                result, entry = future.result()
            except Exception as exc:
                entry = {
                    "kind": "extraction",
                    "batch_index": idx,
                    "window_title": window_title,
                    "section_ids": [s.id for s in batch],
                    "status": "failed",
                    "error": str(exc),
                }
                append_llm_window_log(document.id, entry)
                manifest["llm_windows_completed"] = manifest.get("llm_windows_completed", 0) + 1
                manifest["llm_window_failures"] = manifest.get("llm_window_failures", 0) + 1
                document.artifact_manifest = dict(manifest)
                db.commit()
                continue

            append_llm_window_log(document.id, entry)
            manifest["llm_windows_completed"] = manifest.get("llm_windows_completed", 0) + 1

            rules_in_result = len(result.get("rules", []))
            if rules_in_result:
                print(f"Batch {idx} ({window_title}): got {rules_in_result} rules from {len(batch)} sections", flush=True)

            for raw in result.get("rules", []):
                if not isinstance(raw, dict):
                    continue
                source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
                section_id = source.get("section_id") or raw.get("section_id")
                if not isinstance(section_id, str):
                    section_id = ""
                section = section_by_id.get(section_id) or batch[0]
                try:
                    normalized = normalize_rule(raw, document.id, section)
                except Exception as exc:
                    print(f"Rule normalize error: {exc}", flush=True)
                    append_llm_window_log(
                        document.id,
                        {
                            "kind": "rule_validation",
                            "batch_index": idx,
                            "section_ids": [s.id for s in batch],
                            "status": "failed",
                            "error": str(exc),
                            "raw_rule": raw,
                        },
                    )
                    manifest["llm_window_failures"] = manifest.get("llm_window_failures", 0) + 1
                    document.artifact_manifest = dict(manifest)
                    db.commit()
                    continue
                try:
                    validated = RuleBase.model_validate(normalized)
                    fingerprint = rule_fingerprint(validated.subject, validated.condition, validated.action)
                    rule_id = f"rule-{document.id}-{fingerprint[:12]}"
                    if rule_id in seen_ids:
                        continue
                    seen_ids.add(rule_id)
                    saved_count += save_rule_if_new_batch(db, document, normalized, rule_id=rule_id)
                except Exception as exc:
                    print(f"SAVE ERROR: {type(exc).__name__}: {exc}", flush=True)
                    append_llm_window_log(
                        document.id,
                        {
                            "kind": "rule_validation",
                            "batch_index": idx,
                            "section_ids": [s.id for s in batch],
                            "status": "failed",
                            "error": str(exc),
                            "raw_rule": raw,
                        },
                    )
                    manifest["llm_window_failures"] = manifest.get("llm_window_failures", 0) + 1
                    document.artifact_manifest = dict(manifest)
                    db.commit()

            document.artifact_manifest = dict(manifest)
            if saved_count > 0:
                db.commit()

    failures = int(manifest.get("llm_window_failures", 0))
    if failures == 0:
        stale_rules = db.query(models.Rule).filter(
            models.Rule.document_id == document.id,
            models.Rule.review_status == "draft",
        )
        if seen_ids:
            stale_rules = stale_rules.filter(~models.Rule.id.in_(seen_ids))
        stale_rules.delete(synchronize_session=False)
    db.commit()
    print(f"SAVED {saved_count} rules total", flush=True)
    db_rules = db.query(models.Rule).filter(models.Rule.document_id == document.id).count()
    print(f"DB has {db_rules} rules for document {document.id}", flush=True)

    total = int(manifest.get("llm_windows_total", total_batches))
    if saved_count == 0 and failures:
        document.status = "rule_extraction_failed"
        document.error_message = (
            f"Rule extraction produced no rules. {failures}/{total or failures} LLM windows failed; "
            "check the configured LLM API/base URL and network connectivity."
        )
    else:
        document.status = "rules_extracted"
        document.error_message = None
    db.commit()
    return saved_count


class ExtractionWindow:
    """A group of sections forming one LLM extraction call."""
    __slots__ = ("title", "sections")

    def __init__(self, title: str, sections: list[models.Section]) -> None:
        self.title = title
        self.sections = sections


def split_document_by_level(sections: list[models.Section], level: int) -> list[ExtractionWindow]:
    """Group sections into windows at the given heading level.

    A heading at the target level starts a new window; all deeper sections
    belong to that window. Sections before the first target-level heading
    go into a preamble window."""
    if not sections:
        return []
    windows: list[ExtractionWindow] = []
    current_sections: list[models.Section] = []
    current_title = "Preamble"
    for s in sections:
        if s.level == level:
            if current_sections:
                windows.append(ExtractionWindow(current_title, current_sections))
            current_sections = [s]
            current_title = s.title
        else:
            current_sections.append(s)
    if current_sections:
        windows.append(ExtractionWindow(current_title, current_sections))
    return windows


def gather_definitions(sections: list[models.Section]) -> str:
    """Collect definition-like sections into a global definitions string.

    Uses lightweight heuristics: sections whose heading or first 200 chars
    contain definition keywords."""
    definition_keywords = re.compile(
        r"\b(definition|terminolog|abbreviation|meaning of|interpretation|glossary)\b",
        re.IGNORECASE,
    )
    parts: list[str] = []
    total_chars = 0
    for s in sections:
        heading = " ".join(s.heading_path)
        snippet = s.content[:200] if s.content else ""
        if definition_keywords.search(heading) or definition_keywords.search(snippet):
            text = f"{' > '.join(s.heading_path)}\n{s.content}"
            parts.append(text)
            total_chars += len(text)
            if total_chars > 10000:
                break
    return "\n\n".join(parts)


def build_cross_reference_map(sections: list[models.Section]) -> dict[str, set[str]]:
    """Build map of section_id -> set of referenced section_ids.

    Scans section content for patterns like 'Section A6.2', 'Clause 6.2',
    'see A5.3', then resolves reference text to actual section IDs."""
    ref_map: dict[str, set[str]] = {}
    # Build lookup: reference text variants -> section_id
    id_by_ref: dict[str, str] = {}
    for s in sections:
        # Index by the last numeric segment (e.g. "A6.2" from "Part A > A6 Time > A6.2 Foo")
        for part in s.heading_path:
            match = re.search(r"([A-Z]?\d+(?:\.\d+)*)$", part)
            if match:
                ref_text = match.group(1)
                if ref_text not in id_by_ref:
                    id_by_ref[ref_text] = s.id
        # Also index by title
        match = re.search(r"([A-Z]?\d+(?:\.\d+)*)", s.title)
        if match:
            ref_text = match.group(1)
            if ref_text not in id_by_ref:
                id_by_ref[ref_text] = s.id

    for s in sections:
        refs = detect_references(s.content)
        resolved: set[str] = set()
        for ref in refs:
            target_id = id_by_ref.get(ref)
            if target_id and target_id != s.id:
                resolved.add(target_id)
        if resolved:
            ref_map[s.id] = resolved
    return ref_map


def get_cross_window_refs(
    window: ExtractionWindow,
    window_index_map: dict[str, int],
    cross_ref_map: dict[str, set[str]],
) -> set[str]:
    """Return set of section_ids referenced by this window that live in other windows."""
    window_ids = {s.id for s in window.sections}
    refs: set[str] = set()
    for s in window.sections:
        for ref_id in cross_ref_map.get(s.id, set()):
            if ref_id not in window_ids:
                refs.add(ref_id)
    return refs


def build_chapter_context(
    window: ExtractionWindow,
    definitions: str,
    cross_ref_map: dict[str, set[str]],
    all_sections_by_id: dict[str, models.Section],
    document_id: int,
) -> str:
    """Build shared context for all batches within a chapter window."""
    heading_path = " > ".join(window.sections[0].heading_path) if window.sections else ""
    context = (
        f"Document ID: {document_id}\n"
        f"Chapter: {window.title}\n"
        f"Heading Path: {heading_path}\n"
        f"Global definitions:\n{definitions[:4000] or '(none provided)'}\n"
    )
    # Cross-reference context
    cross_refs = get_cross_window_refs(window, {}, cross_ref_map)
    if cross_refs:
        ref_blocks: list[str] = []
        injected = 0
        for ref_id in cross_refs:
            if injected >= 5:
                break
            ref_section = all_sections_by_id.get(ref_id)
            if ref_section:
                block = (
                    f"[Section {ref_section.title}]\n"
                    f"Heading: {' > '.join(ref_section.heading_path)}\n"
                    f"Content:\n{ref_section.content[:3000]}"
                )
                ref_blocks.append(block)
                injected += 1
        if ref_blocks:
            context += (
                "\n### CROSS-REFERENCE CONTEXT ###\n"
                "Referenced sections (for context only, do NOT extract rules from these):\n"
                + "\n---\n".join(ref_blocks)
                + "\n### END CROSS-REFERENCE CONTEXT ###\n"
            )
    return context


def build_batch_extraction_prompt(
    batch: list[dict[str, Any]],
    chapter_context: str,
) -> str:
    """Build prompt for a batch of sections within a chapter."""
    sections_text = "\n\n---\n\n".join(
        (
            f"SECTION_ID: {s['id']}\n"
            f"HEADING_PATH: {' > '.join(s['heading_path'])}\n"
            f"TEXT:\n{s['content']}"
        )
        for s in batch
    )
    return (
        f"{chapter_context}\n"
        f"Extract ALL rules from EACH of the following {len(batch)} sections. "
        "Review every section — skip only if truly empty/whitespace.\n\n"
        f"{sections_text}\n\n"
        "Return JSON only: {\"rules\": [...]}. "
        "source must be an object with heading_path, section_id, evidence_text, page_range, coordinates. "
        "review_status must be \"draft\"."
    )


def extract_rules_from_batch(
    llm: LLMClient,
    system_prompt: str,
    window_title: str,
    batch: list[dict[str, Any]],
    chapter_context: str,
    batch_index: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Extract rules from one batch of sections with shared chapter context."""
    prompt = build_batch_extraction_prompt(batch, chapter_context)
    result = llm.complete_json(system_prompt, prompt)
    entry = {
        "kind": "extraction",
        "batch_index": batch_index,
        "window_title": window_title,
        "section_ids": [s["id"] for s in batch],
        "prompt": prompt,
        "response": result,
        "status": "completed",
    }
    return result, entry


def section_snapshot(section: models.Section) -> dict[str, Any]:
    """Copy the values workers need so SQLAlchemy objects never cross threads."""
    return {
        "id": section.id,
        "title": section.title,
        "content": section.content,
        "heading_path": list(section.heading_path or []),
    }


def append_llm_window_log(document_id: int, entry: dict[str, Any]) -> None:
    path = llm_windows_path(document_id)
    safe_entry = sanitize_export(entry)
    safe_entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe_entry, ensure_ascii=False) + "\n")


def llm_windows_path(document_id: int) -> Path:
    return document_storage_dir(document_id) / "llm_windows.jsonl"


def sanitize_export(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("***REDACTED***" if "key" in key.lower() or "token" in key.lower() else sanitize_export(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_export(item) for item in value]
    return value


def detect_references(text: str) -> list[str]:
    refs = re.findall(r"(?:Section\s+)?((?:[A-Z]\d+|\d+)(?:\.\d+){1,5})", text)
    seen: list[str] = []
    for ref in refs:
        if ref not in seen:
            seen.append(ref)
    return seen[:20]


def _section_attr(section: models.Section | dict[str, Any], key: str, default: Any = "") -> Any:
    """Read *key* from a SQLAlchemy model or dict, falling back to *default* when missing or falsy."""
    if hasattr(section, key):
        val = getattr(section, key)
    elif isinstance(section, dict):
        val = section.get(key, default)
    else:
        return default
    return val if val else default


def normalize_rule(raw: dict[str, Any], document_id: int, section: models.Section | dict[str, Any]) -> dict[str, Any]:
    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    if not source and raw.get("source"):
        source = {"evidence_text": str(raw.get("source"))}
    raw["source"] = normalize_source(source, raw, section)
    raw["document_id"] = document_id
    raw["section_id"] = _section_attr(section, "id", "")
    raw["type"] = normalize_rule_type(raw.get("type"))
    raw["review_status"] = normalize_review_status(raw.get("review_status"))
    raw["confidence"] = coerce_confidence(raw.get("confidence"))
    raw["subject"] = normalize_text(raw.get("subject"), fallback=_section_attr(section, "title"))
    raw["condition"] = normalize_text(raw.get("condition"))
    raw["action"] = normalize_text(raw.get("action"), fallback=_section_attr(section, "content"))
    raw["actor"] = normalize_optional_text(raw.get("actor"))
    raw["target"] = normalize_optional_text(raw.get("target"))
    raw["deadline"] = normalize_optional_text(raw.get("deadline"))
    raw["notes"] = normalize_text(raw.get("notes"))
    raw["options"] = normalize_options(raw.get("options"))
    raw["dependencies"] = normalize_dependencies(raw.get("dependencies"))
    raw["next_rule_ids"] = normalize_string_list(raw.get("next_rule_ids"))
    return raw


def normalize_source(source: dict[str, Any], raw: dict[str, Any], section: models.Section | dict[str, Any]) -> dict[str, Any]:
    heading_path = source.get("heading_path")
    if not isinstance(heading_path, list):
        heading_path = _section_attr(section, "heading_path", [])
    coordinates = source.get("coordinates")
    if not isinstance(coordinates, list):
        coordinates = []
    evidence_text = source.get("evidence_text")
    if evidence_text is None:
        evidence_text = raw.get("evidence_text") or ""
    section_id = source.get("section_id") or _section_attr(section, "id", "")
    return {
        "heading_path": [str(item) for item in heading_path],
        "section_id": section_id,
        "page_range": normalize_optional_text(source.get("page_range")),
        "evidence_text": str(evidence_text),
        "coordinates": coordinates,
    }


def normalize_options(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    options: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            options.append(
                {
                    "label": str(item.get("label") or item.get("name") or ""),
                    "condition": normalize_text(item.get("condition")),
                    "action": normalize_text(item.get("action") or item.get("description")),
                    "next_rule_ids": normalize_string_list(item.get("next_rule_ids")),
                    "referenced_sections": normalize_string_list(item.get("referenced_sections")),
                }
            )
        elif item:
            options.append(
                {
                    "label": str(item),
                    "condition": "",
                    "action": str(item),
                    "next_rule_ids": [],
                    "referenced_sections": [],
                }
            )
    return options


def normalize_dependencies(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    dependencies: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            dependencies.append(
                {
                    "type": item.get("type") if item.get("type") in {"requires", "leads_to", "alternative_to", "references"} else "references",
                    "rule_id": normalize_text(item.get("rule_id")),
                    "reason": normalize_text(item.get("reason")),
                }
            )
        elif item:
            dependencies.append({"type": "references", "rule_id": "", "reason": str(item)})
    return dependencies


def coerce_confidence(value: Any) -> float:
    if isinstance(value, (int, float)):
        return min(1.0, max(0.0, float(value)))
    return 0.5


def normalize_rule_type(value: Any) -> str:
    normalized = str(value or "procedure").strip().lower()
    normalized = TYPE_ALIASES.get(normalized, normalized)
    return normalized if normalized in VALID_RULE_TYPES else "procedure"


def normalize_review_status(value: Any) -> str:
    normalized = str(value or "draft").strip().lower()
    return normalized if normalized in {"draft", "reviewed", "rejected"} else "draft"


def normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = normalize_text(value)
    return text or None


def normalize_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, list):
        return "; ".join(normalize_text(item) for item in value if item is not None)
    if isinstance(value, dict):
        return "; ".join(f"{key}: {normalize_text(item)}" for key, item in value.items())
    return str(value)


def normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [normalize_text(item) for item in value if normalize_text(item)]


def save_rule_if_new(db: Session, document: models.Document, raw: dict[str, Any]) -> int:
    validated = RuleBase.model_validate(raw)
    fingerprint = rule_fingerprint(validated.subject, validated.condition, validated.action)
    rule_id = f"rule-{document.id}-{fingerprint[:12]}"
    existing = db.query(models.Rule).filter(models.Rule.id == rule_id).first()
    if existing:
        if existing.review_status not in {"reviewed", "rejected"}:
            existing.section_id = raw.get("section_id")
            existing.source = validated.source.model_dump()
            existing.subject = validated.subject
            existing.condition = validated.condition
            existing.action = validated.action
            existing.type = validated.type
            existing.actor = validated.actor
            existing.target = validated.target
            existing.deadline = validated.deadline
            existing.options = [option.model_dump() for option in validated.options]
            existing.dependencies = [dependency.model_dump() for dependency in validated.dependencies]
            existing.next_rule_ids = validated.next_rule_ids
            existing.confidence = validated.confidence
            existing.notes = validated.notes
        return 0
    db.add(
        models.Rule(
            id=rule_id,
            document_id=document.id,
            section_id=raw.get("section_id"),
            source=validated.source.model_dump(),
            subject=validated.subject,
            condition=validated.condition,
            action=validated.action,
            type=validated.type,
            actor=validated.actor,
            target=validated.target,
            deadline=validated.deadline,
            options=[option.model_dump() for option in validated.options],
            dependencies=[dependency.model_dump() for dependency in validated.dependencies],
            next_rule_ids=validated.next_rule_ids,
            confidence=validated.confidence,
            review_status=validated.review_status,
            notes=validated.notes,
        )
    )
    db.commit()
    return 1


def save_rule_if_new_batch(db: Session, document: models.Document, raw: dict[str, Any], rule_id: str | None = None) -> int:
    """Like save_rule_if_new but does NOT commit - caller manages the transaction."""
    validated = RuleBase.model_validate(raw)
    if rule_id is None:
        fingerprint = rule_fingerprint(validated.subject, validated.condition, validated.action)
        rule_id = f"rule-{document.id}-{fingerprint[:12]}"
    existing = db.query(models.Rule).filter(models.Rule.id == rule_id).first()
    if existing:
        return 0
    db.add(
        models.Rule(
            id=rule_id,
            document_id=document.id,
            section_id=raw.get("section_id"),
            source=validated.source.model_dump(),
            subject=validated.subject,
            condition=validated.condition,
            action=validated.action,
            type=validated.type,
            actor=validated.actor,
            target=validated.target,
            deadline=validated.deadline,
            options=[option.model_dump() for option in validated.options],
            dependencies=[dependency.model_dump() for dependency in validated.dependencies],
            next_rule_ids=validated.next_rule_ids,
            confidence=validated.confidence,
            review_status=validated.review_status,
            notes=validated.notes,
        )
    )
    return 1


def rule_fingerprint(subject: str, condition: str, action: str) -> str:
    payload = " ".join([subject.strip().lower(), condition.strip().lower(), action.strip().lower()])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def chunked(items: list, size: int) -> list[list]:
    return [items[index : index + size] for index in range(0, len(items), size)]
