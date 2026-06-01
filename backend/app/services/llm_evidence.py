from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .. import models
from ..runtime_config import get_runtime_config
from .llm import LLMClient, LLMError


def gather_tender_sections(db: Session, submission: models.TenderSubmission) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    for source_id in submission.source_document_ids:
        source = db.query(models.SourceDocument).filter(models.SourceDocument.id == source_id).first()
        if not source or not source.linked_document_id:
            continue
        rows = (
            db.query(models.Section)
            .filter(models.Section.document_id == source.linked_document_id)
            .order_by(models.Section.position)
            .all()
        )
        for section in rows:
            content = (section.content or "").strip()
            if not content:
                continue
            sections.append((section.title or "", content))
    return sections


def extract_evidence_value(
    db: Session, submission: models.TenderSubmission, field: models.TemplateField
) -> tuple[str, str, float, bool]:
    """LLM-extract the value for a tender template field from the tender's sections.

    Returns (value, raw_excerpt, confidence, found).
    """
    sections = gather_tender_sections(db, submission)
    if not sections:
        return "", "", 0.0, False
    config = get_runtime_config()
    client = LLMClient(api_key=config.llm_api_key, model=config.llm_model)
    sections_payload = [
        {"title": title, "content": content[:1500]} for title, content in sections[:80]
    ]
    system_prompt = (
        "You extract a single value from a tender document for a specific template field.\n"
        "The value is what a human reviewer would write in this field when filling in a tender response.\n\n"
        "Return JSON only:\n"
        '{"value": "...", "raw_excerpt": "exact source text or empty", "confidence": 0.0-1.0, "found": true|false}\n\n'
        "Rules:\n"
        "- If the tender states a value, return it in `value` and a verbatim quote in `raw_excerpt`.\n"
        "- If the tender does not state the value, set `found=false` and return empty value/excerpt.\n"
        "- Keep the value short (one sentence or a single value).\n"
        "- Confidence is your best estimate of how clearly the value is stated (0.0-1.0)."
    )
    user_prompt = (
        "TEMPLATE FIELD:\n"
        f"- field_key: {field.field_key}\n"
        f"- label: {field.label}\n"
        f"- anchor_text: {field.anchor_text or '(none)'}\n"
        f"- extraction_hint: {field.extraction_hint or '(none)'}\n"
        f"- input_type: {field.input_type}\n\n"
        f"TENDER DOCUMENT SECTIONS ({len(sections_payload)}):\n"
        f"{json.dumps(sections_payload, ensure_ascii=False, indent=2)}\n\n"
        "Extract the value for this field."
    )
    try:
        response = client.complete_json(system_prompt, user_prompt)
    except LLMError as exc:
        return "", f"LLM extraction failed: {exc}", 0.0, False
    return (
        str(response.get("value", "")).strip(),
        str(response.get("raw_excerpt", "")).strip(),
        float(response.get("confidence", 0.0) or 0.0),
        bool(response.get("found", False)),
    )
