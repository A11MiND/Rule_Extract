from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..schemas import RuleBase
from .llm import DoubaoClient


CLASSIFY_SYSTEM_PROMPT = """You classify sections from NEC public works Practice Notes.
Return JSON only with keys: classification, confidence, reason.
classification must be one of: background, definition, rule_candidate, mixed."""

EXTRACT_SYSTEM_PROMPT = """You extract evidence-backed rules from NEC public works Practice Notes.
Return JSON only with key rules. rules must be an array.
Each rule must include source, subject, condition, action, type, actor, target, deadline,
options, dependencies, next_rule_ids, confidence, review_status, notes.
Use only the provided text. If text is background, return an empty rules array.
Use type from obligation, prohibition, permission, definition, procedure, deadline, option,
checklist, background."""


def classify_sections(db: Session, document: models.Document, llm: DoubaoClient) -> None:
    for section in document.sections:
        prompt = (
            f"Heading path: {' > '.join(section.heading_path)}\n\n"
            f"Section text:\n{section.content[:6000]}"
        )
        result = llm.complete_json(CLASSIFY_SYSTEM_PROMPT, prompt)
        section.classification = str(result.get("classification") or "mixed")
        confidence = result.get("confidence", 0.5)
        section.classification_confidence = float(confidence if isinstance(confidence, (int, float)) else 0.5)
    db.commit()


def extract_rules(db: Session, document: models.Document, llm: DoubaoClient) -> int:
    definitions = "\n\n".join(
        f"{' > '.join(section.heading_path)}\n{section.content}"
        for section in document.sections
        if section.classification == "definition"
    )[:10000]

    raw_rules: list[dict[str, Any]] = []
    for section in document.sections:
        if section.classification == "background":
            continue
        prompt = build_extraction_prompt(section, definitions)
        result = llm.complete_json(EXTRACT_SYSTEM_PROMPT, prompt)
        for raw in result.get("rules", []):
            if isinstance(raw, dict):
                raw_rules.append(normalize_rule(raw, document.id, section))

    saved = reconcile_and_save_rules(db, document, raw_rules)
    document.status = "rules_extracted"
    db.commit()
    return saved


def build_extraction_prompt(section: models.Section, definitions: str) -> str:
    return (
        f"Document ID: {section.document_id}\n"
        f"Current section ID: {section.id}\n"
        f"Heading path: {' > '.join(section.heading_path)}\n\n"
        f"Global definitions and abbreviations:\n{definitions or '(none provided)'}\n\n"
        f"Section text:\n{section.content[:12000]}\n\n"
        "Extract rules with direct evidence. For option branches, populate options and next_rule_ids "
        "only when the text supports them."
    )


def normalize_rule(raw: dict[str, Any], document_id: int, section: models.Section) -> dict[str, Any]:
    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    source.setdefault("heading_path", section.heading_path)
    source.setdefault("section_id", section.id)
    source.setdefault("evidence_text", raw.get("evidence_text") or "")
    raw["source"] = source
    raw["document_id"] = document_id
    raw["section_id"] = section.id
    raw["review_status"] = raw.get("review_status") or "draft"
    raw["confidence"] = coerce_confidence(raw.get("confidence"))
    raw["options"] = raw.get("options") if isinstance(raw.get("options"), list) else []
    raw["dependencies"] = raw.get("dependencies") if isinstance(raw.get("dependencies"), list) else []
    raw["next_rule_ids"] = raw.get("next_rule_ids") if isinstance(raw.get("next_rule_ids"), list) else []
    return raw


def coerce_confidence(value: Any) -> float:
    if isinstance(value, (int, float)):
        return min(1.0, max(0.0, float(value)))
    return 0.5


def reconcile_and_save_rules(db: Session, document: models.Document, raw_rules: list[dict[str, Any]]) -> int:
    db.query(models.Rule).filter(models.Rule.document_id == document.id).delete()
    seen: set[str] = set()
    saved = 0
    for raw in raw_rules:
        validated = RuleBase.model_validate(raw)
        fingerprint = rule_fingerprint(validated.subject, validated.condition, validated.action)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        rule_id = f"rule-{document.id}-{saved + 1:03d}-{fingerprint[:8]}"
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
        saved += 1
    db.commit()
    return saved


def rule_fingerprint(subject: str, condition: str, action: str) -> str:
    payload = " ".join([subject.strip().lower(), condition.strip().lower(), action.strip().lower()])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()
