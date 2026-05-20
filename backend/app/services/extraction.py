from __future__ import annotations

import hashlib
import re
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..schemas import RuleBase
from .llm import DoubaoClient


CLASSIFY_SYSTEM_PROMPT = """You classify sections from NEC public works Practice Notes.
Return JSON only with key sections. sections must be an array.
Each item must include id, classification, confidence, reason.
classification must be one of: background, definition, rule_candidate, mixed."""

EXTRACT_SYSTEM_PROMPT = """You extract evidence-backed rules from NEC public works Practice Notes.
Return JSON only with key rules. rules must be an array.
Each rule must include source, subject, condition, action, type, actor, target, deadline,
options, dependencies, next_rule_ids, confidence, review_status, notes.
Use only the provided text. If text is background, return an empty rules array.
Use type from obligation, prohibition, permission, definition, procedure, deadline, option,
checklist, background."""

DEMO_MAX_EXTRACTION_SECTIONS = 24
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


def classify_sections(db: Session, document: models.Document, llm: DoubaoClient) -> None:
    for section in document.sections:
        section.classification, section.classification_confidence = classify_section_heuristic(section)
    db.commit()


def extract_rules(db: Session, document: models.Document, llm: DoubaoClient) -> int:
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
        if section.classification != "background" and section.content.strip()
    ][:DEMO_MAX_EXTRACTION_SECTIONS]
    for batch in chunked(candidate_sections, 3):
        section_by_id = {section.id: section for section in batch}
        prompt = build_extraction_prompt(batch, definitions)
        result = llm.complete_json(EXTRACT_SYSTEM_PROMPT, prompt)
        for raw in result.get("rules", []):
            if isinstance(raw, dict):
                source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
                section_id = source.get("section_id") or raw.get("section_id")
                section = section_by_id.get(section_id) or batch[0]
                saved += save_rule_if_new(db, document, normalize_rule(raw, document.id, section))

    document.status = "rules_extracted"
    db.commit()
    return saved


def build_extraction_prompt(sections: list[models.Section], definitions: str) -> str:
    return (
        f"Document ID: {sections[0].document_id}\n"
        f"Global definitions and abbreviations:\n{definitions[:4000] or '(none provided)'}\n\n"
        "Sections:\n"
        + "\n\n".join(
            (
                f"SECTION_ID: {section.id}\n"
                f"HEADING_PATH: {' > '.join(section.heading_path)}\n"
                f"TEXT:\n{section.content[:1800]}"
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
    raw["actor"] = normalize_optional_text(raw.get("actor"))
    raw["target"] = normalize_optional_text(raw.get("target"))
    raw["deadline"] = normalize_optional_text(raw.get("deadline"))
    raw["notes"] = str(raw.get("notes") or "")
    raw["options"] = normalize_options(raw.get("options"))
    raw["dependencies"] = normalize_dependencies(raw.get("dependencies"))
    raw["next_rule_ids"] = raw.get("next_rule_ids") if isinstance(raw.get("next_rule_ids"), list) else []
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
        "heading_path": heading_path,
        "section_id": source.get("section_id") or section.id,
        "page_range": source.get("page_range"),
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
                    "condition": str(item.get("condition") or ""),
                    "action": str(item.get("action") or item.get("description") or ""),
                    "next_rule_ids": item.get("next_rule_ids") if isinstance(item.get("next_rule_ids"), list) else [],
                    "referenced_sections": item.get("referenced_sections")
                    if isinstance(item.get("referenced_sections"), list)
                    else [],
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
                    "rule_id": str(item.get("rule_id") or ""),
                    "reason": str(item.get("reason") or ""),
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
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item is not None)
    if isinstance(value, dict):
        return ", ".join(f"{key}: {item}" for key, item in value.items())
    return str(value)


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
