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


CLASSIFY_SYSTEM_PROMPT = """You classify sections from NEC public works Practice Notes.
Return JSON only with key sections. sections must be an array.
Each item must include id, classification, confidence, reason.
classification must be one of: background, definition, rule_candidate, option_logic, mixed, table_only."""

EXTRACT_SYSTEM_PROMPT = """You extract evidence-backed rules from NEC public works Practice Notes.
Return JSON only with key rules. rules must be an array.
Each rule must include source, subject, condition, action, type, actor, target, deadline,
options, dependencies, next_rule_ids, confidence, review_status, notes.
Use only the provided text. If text is background, return an empty rules array.
Use type from obligation, prohibition, permission, definition, procedure, deadline, option,
checklist, background."""

EXTRACTION_BATCH_SIZE = 3
CLASSIFICATION_BATCH_SIZE = 12
MAX_PROMPT_CHARS_PER_SECTION = 2200
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


def classify_sections(
    db: Session,
    document: models.Document,
    llm: LLMClient,
    concurrency: int = 8,
) -> None:
    sections = list(document.sections)
    for batch_index, batch in enumerate(chunked(sections, CLASSIFICATION_BATCH_SIZE), start=1):
        prompt = build_classification_prompt(batch)
        entry: dict[str, Any] = {
            "kind": "classification",
            "batch_index": batch_index,
            "section_ids": [section.id for section in batch],
            "prompt": prompt,
            "status": "completed",
        }
        try:
            result = llm.complete_json(CLASSIFY_SYSTEM_PROMPT, prompt)
            entry["response"] = result
            by_id = {
                item.get("id"): item
                for item in result.get("sections", [])
                if isinstance(item, dict)
            }
            for section in batch:
                item = by_id.get(section.id) or {}
                classification = str(item.get("classification") or "")
                if classification not in {
                    "background",
                    "definition",
                    "rule_candidate",
                    "option_logic",
                    "mixed",
                    "table_only",
                }:
                    classification, confidence = classify_section_heuristic(section)
                else:
                    confidence = coerce_confidence(item.get("confidence"))
                section.classification = classification
                section.classification_confidence = confidence
        except Exception as exc:
            entry["status"] = "failed"
            entry["error"] = str(exc)
            for section in batch:
                section.classification, section.classification_confidence = classify_section_heuristic(section)
        append_llm_window_log(document.id, entry)
        update_window_progress(db, document, completed_delta=1)
    db.commit()


def extract_rules(
    db: Session,
    document: models.Document,
    llm: LLMClient,
    concurrency: int = 8,
) -> int:
    definitions = "\n\n".join(
        f"{' > '.join(section.heading_path)}\n{section.content}"
        for section in document.sections
        if section.classification == "definition"
    )[:10000]

    db.query(models.Rule).filter(models.Rule.document_id == document.id).delete()
    db.commit()
    saved = 0
    candidate_sections = [
        section
        for section in document.sections
        if section.classification not in {"background", "table_only"} and section.content.strip()
    ]
    batches = chunked(candidate_sections, EXTRACTION_BATCH_SIZE)
    set_window_totals(db, document, total=len(batches))
    if not batches:
        document.status = "rules_extracted"
        db.commit()
        return 0

    max_workers = clamp_concurrency(concurrency)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(extract_rule_window, llm, batch, definitions, index): (index, batch)
            for index, batch in enumerate(batches, start=1)
        }
        for future in as_completed(futures):
            index, batch = futures[future]
            section_by_id = {section.id: section for section in batch}
            try:
                result, entry = future.result()
            except Exception as exc:
                entry = {
                    "kind": "extraction",
                    "batch_index": index,
                    "section_ids": [section.id for section in batch],
                    "status": "failed",
                    "error": str(exc),
                }
                append_llm_window_log(document.id, entry)
                update_window_progress(db, document, completed_delta=1, failure_delta=1)
                continue
            append_llm_window_log(document.id, entry)
            update_window_progress(db, document, completed_delta=1)
            for raw in result.get("rules", []):
                if isinstance(raw, dict):
                    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
                    section_id = source.get("section_id") or raw.get("section_id")
                    section = section_by_id.get(section_id) or batch[0]
                    try:
                        saved += save_rule_if_new(db, document, normalize_rule(raw, document.id, section))
                    except Exception as exc:
                        append_llm_window_log(
                            document.id,
                            {
                                "kind": "rule_validation",
                                "batch_index": index,
                                "section_ids": [section.id for section in batch],
                                "status": "failed",
                                "error": str(exc),
                                "raw_rule": raw,
                            },
                        )
                        update_window_progress(db, document, failure_delta=1)

    document.status = "rules_extracted"
    db.commit()
    return saved


def extract_rule_window(
    llm: LLMClient,
    batch: list[models.Section],
    definitions: str,
    batch_index: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt = build_extraction_prompt(batch, definitions)
    result = llm.complete_json(EXTRACT_SYSTEM_PROMPT, prompt)
    entry = {
        "kind": "extraction",
        "batch_index": batch_index,
        "section_ids": [section.id for section in batch],
        "prompt": prompt,
        "response": result,
        "status": "completed",
    }
    return result, entry


def build_classification_prompt(sections: list[models.Section]) -> str:
    return (
        "Classify the following sections for rule extraction. Return JSON only: "
        '{"sections":[{"id":"...","classification":"rule_candidate","confidence":0.8,"reason":"..."}]}.\n\n'
        + "\n\n".join(
            (
                f"SECTION_ID: {section.id}\n"
                f"HEADING_PATH: {' > '.join(section.heading_path)}\n"
                f"DETECTED_REFERENCES: {', '.join(detect_references(section.content)) or '(none)'}\n"
                f"TEXT:\n{section.content[:900]}"
            )
            for section in sections
        )
    )


def build_extraction_prompt(sections: list[models.Section], definitions: str) -> str:
    return (
        f"Document ID: {sections[0].document_id}\n"
        f"Global definitions and abbreviations:\n{definitions[:4000] or '(none provided)'}\n\n"
        "Sections:\n"
        + "\n\n".join(
            (
                f"SECTION_ID: {section.id}\n"
                f"HEADING_PATH: {' > '.join(section.heading_path)}\n"
                f"DETECTED_REFERENCES: {', '.join(detect_references(section.content)) or '(none)'}\n"
                f"TEXT:\n{section.content[:MAX_PROMPT_CHARS_PER_SECTION]}"
            )
            for section in sections
        )
        + "\n\nReturn JSON only: {\"rules\": [...]}."
        " Extract at most 3 evidence-backed rules per section batch."
        " For every rule, source must be an object with heading_path, section_id, evidence_text,"
        " page_range, and coordinates."
        " type must be one of: obligation, prohibition, permission, definition, procedure,"
        " deadline, option, checklist, background."
        " review_status must be draft."
        " For option branches, populate options and next_rule_ids only when the text supports them."
    )


def append_llm_window_log(document_id: int, entry: dict[str, Any]) -> None:
    path = llm_windows_path(document_id)
    safe_entry = sanitize_export(entry)
    safe_entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe_entry, ensure_ascii=False) + "\n")


def llm_windows_path(document_id: int) -> Path:
    return document_storage_dir(document_id) / "llm_windows.jsonl"


def update_window_progress(
    db: Session,
    document: models.Document,
    completed_delta: int = 0,
    failure_delta: int = 0,
) -> None:
    manifest = dict(document.artifact_manifest or {})
    manifest["llm_windows_completed"] = int(manifest.get("llm_windows_completed") or 0) + completed_delta
    manifest["llm_window_failures"] = int(manifest.get("llm_window_failures") or 0) + failure_delta
    manifest["llm_windows_path"] = str(llm_windows_path(document.id))
    document.artifact_manifest = manifest
    db.commit()


def set_window_totals(db: Session, document: models.Document, total: int) -> None:
    manifest = dict(document.artifact_manifest or {})
    manifest["llm_windows_total"] = total
    manifest["llm_windows_completed"] = 0
    manifest["llm_window_failures"] = 0
    manifest["llm_windows_path"] = str(llm_windows_path(document.id))
    document.artifact_manifest = manifest
    db.commit()


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


def normalize_rule(raw: dict[str, Any], document_id: int, section: models.Section) -> dict[str, Any]:
    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    if not source and raw.get("source"):
        source = {"evidence_text": str(raw.get("source"))}
    raw["source"] = normalize_source(source, raw, section)
    raw["document_id"] = document_id
    raw["section_id"] = section.id
    raw["type"] = normalize_rule_type(raw.get("type"))
    raw["review_status"] = normalize_review_status(raw.get("review_status"))
    raw["confidence"] = coerce_confidence(raw.get("confidence"))
    raw["subject"] = normalize_text(raw.get("subject"), fallback=section.title)
    raw["condition"] = normalize_text(raw.get("condition"))
    raw["action"] = normalize_text(raw.get("action"), fallback=section.content or section.title)
    raw["actor"] = normalize_optional_text(raw.get("actor"))
    raw["target"] = normalize_optional_text(raw.get("target"))
    raw["deadline"] = normalize_optional_text(raw.get("deadline"))
    raw["notes"] = normalize_text(raw.get("notes"))
    raw["options"] = normalize_options(raw.get("options"))
    raw["dependencies"] = normalize_dependencies(raw.get("dependencies"))
    raw["next_rule_ids"] = normalize_string_list(raw.get("next_rule_ids"))
    return raw


def normalize_source(source: dict[str, Any], raw: dict[str, Any], section: models.Section) -> dict[str, Any]:
    heading_path = source.get("heading_path")
    if not isinstance(heading_path, list):
        heading_path = section.heading_path
    coordinates = source.get("coordinates")
    if not isinstance(coordinates, list):
        coordinates = []
    evidence_text = source.get("evidence_text")
    if evidence_text is None:
        evidence_text = raw.get("evidence_text") or ""
    return {
        "heading_path": [str(item) for item in heading_path],
        "section_id": source.get("section_id") or section.id,
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


def rule_fingerprint(subject: str, condition: str, action: str) -> str:
    payload = " ".join([subject.strip().lower(), condition.strip().lower(), action.strip().lower()])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def chunked(items: list[models.Section], size: int) -> list[list[models.Section]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def classify_section_heuristic(section: models.Section) -> tuple[str, float]:
    heading = " ".join(section.heading_path).lower()
    text = section.content.lower()
    combined = f"{heading}\n{text}"
    if not text.strip() and not re.search(r"\b(option|clause|tender|contract|shall|should)\b", heading):
        return "background", 0.8
    if re.search(r"\b(definition|terminolog|abbreviation|meaning of|interpretation)\b", combined):
        return "definition", 0.72
    if re.search(r"\b(background|history|executive summary|contents|general information)\b", heading):
        return "background", 0.7
    if re.search(
        r"\b(shall|should|must|required|requirement|submit|review|check|approve|include|"
        r"determine|assess|option|clause|procedure|tender document|project office)\b",
        combined,
    ):
        return "rule_candidate", 0.68
    return "mixed", 0.55
