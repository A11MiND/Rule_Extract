from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..runtime_config import effective_llm_key, get_runtime_config
from .llm import LLMClient, LLMError


TEMPLATE_FIELD_SYSTEM_PROMPT = """\
You extract reviewable tender-template fields from converted PDF markdown.

Return JSON only:
{
  "fields": [
    {
      "field_key": "stable.snake_case.key",
      "label": "Human label for the field",
      "check_intent": "What a future tender reviewer must verify",
      "part_ref": "Part / section reference if visible",
      "filled_by": "project_office|bidder|system_derived|unknown",
      "anchor_text": "Nearby source wording containing the placeholder or table",
      "input_type": "text|enum|list|date|money|percentage|table|signature_block|file_list|checklist",
      "structured_schema": {"columns": [], "repeatable": false},
      "normalization": {"format": "plain_text"},
      "required": true,
      "section_ref": "section id from input",
      "extraction_hint": "How to extract this field from a completed tender",
      "confidence": 0.0,
      "rationale": "Why this is a reviewable fillable field"
    }
  ]
}

Rules:
- Extract fields that require human/template completion or tender checking.
- Identify fillable placeholders, blank cells, tables, signature areas, tenderer/project-office inputs, and checkable template clauses from the markdown yourself.
- Treat tables, graphs, schedules, and repeated rows as structured fields with a useful structured_schema.
- Infer ownership per field. Bidder/tenderer supplied values use filled_by=bidder; calculated values use system_derived.
- Do not rely on pre-extracted marker candidates; the input sections are the source of truth.
- Do not emit decorative headings, page numbers, or instructions that do not represent a checkable field.
- field_key must be stable and generic; do not invent document-specific database ids.
- Every field must cite a section_ref from the input when possible.
"""


def build_template_fields(source: models.SourceDocument, db: Session) -> list[dict[str, object]]:
    template_doc = infer_template_doc(source.name)
    text_sections = []
    if source.linked_document_id:
        text_sections = (
            db.query(models.Section)
            .filter(models.Section.document_id == source.linked_document_id)
            .order_by(models.Section.position)
            .all()
        )
    llm_fields = llm_extract_template_fields(source, template_doc, text_sections)
    return dedupe_field_candidates(llm_fields)


def llm_extract_template_fields(
    source: models.SourceDocument,
    template_doc: str,
    sections: list[models.Section],
) -> list[dict[str, object]]:
    if not sections:
        return []
    config = get_runtime_config()
    client = LLMClient(
        api_base=config.llm_api_base,
        api_key=effective_llm_key(config),
        model=config.llm_model,
        provider=config.llm_provider,
    )
    section_map = {section.id: section for section in sections}
    fields: list[dict[str, object]] = []
    for window in chunk_reviewable_sections(sections, size=8):
        payload = {
            "template_doc": template_doc,
            "source_document": source.name,
            "sections": [
                {
                    "section_id": section.id,
                    "position": section.position,
                    "level": section.level,
                    "heading_path": section.heading_path,
                    "title": section.title,
                    "text": normalize_space(f"{section.title}\n{section.content}")[:3500],
                }
                for section in window
            ],
        }
        try:
            response = client.complete_json(TEMPLATE_FIELD_SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False))
        except LLMError:
            continue
        raw_fields = response.get("fields")
        if not isinstance(raw_fields, list):
            continue
        for raw in raw_fields:
            normalized = normalize_llm_field(raw, source, template_doc, section_map, len(fields) + 1)
            if normalized:
                fields.append(normalized)
    return fields


def chunk_reviewable_sections(
    sections: list[models.Section],
    size: int = 8,
) -> list[list[models.Section]]:
    reviewable = [
        section for section in sections[:320]
        if normalize_space(f"{section.title}\n{section.content}")
    ]
    return [reviewable[index:index + size] for index in range(0, len(reviewable), size)]


def normalize_llm_field(
    raw: Any,
    source: models.SourceDocument,
    template_doc: str,
    section_map: dict[str, models.Section],
    index: int,
) -> dict[str, object] | None:
    if not isinstance(raw, dict):
        return None
    label = clean_label_text(str(raw.get("label") or raw.get("field_key") or ""))
    if not label or is_low_value_template_label(label):
        return None
    section_ref = str(raw.get("section_ref") or "")
    section = section_map.get(section_ref) or next(iter(section_map.values()), None)
    try:
        confidence = float(raw.get("confidence", 0.7))
    except (TypeError, ValueError):
        confidence = 0.7
    raw_key = str(raw.get("field_key") or "").strip()
    field_key = ".".join(part for part in (slugify(piece) for piece in raw_key.split(".")) if part)
    if not field_key:
        field_key = f"{template_doc.lower()}.llm.{section.position if section else index}.{slugify(label)[:48]}"
    elif "." not in field_key:
        field_key = f"{template_doc.lower()}.{field_key}"
    anchor_text = str(raw.get("anchor_text") or "")
    if not anchor_text and section:
        anchor_text = normalize_space(f"{section.title}\n{section.content}")[:500]
    return {
        "collection_id": source.collection_id,
        "source_document_id": source.id,
        "template_doc": template_doc,
        "field_key": field_key[:120],
        "label": label[:180],
        "anchor_text": anchor_text[:700],
        "input_type": normalize_input_type(str(raw.get("input_type") or infer_input_type(f"{label} {anchor_text}"))),
        "required": bool(raw.get("required", True)),
        "section_ref": section_ref if section_ref in section_map else (section.id if section else None),
        "extraction_hint": str(raw.get("extraction_hint") or f"Extract the completed tender value for '{label}'.")[:260],
        "check_intent": str(raw.get("check_intent") or f"Verify the completed value for '{label}'.")[:500],
        "structured_schema": raw.get("structured_schema") if isinstance(raw.get("structured_schema"), dict) else {},
        "normalization": raw.get("normalization") if isinstance(raw.get("normalization"), dict) else {},
        "evidence_locator": {
            "source_document_id": source.id,
            "document_id": source.linked_document_id,
            "section_id": section.id if section else section_ref,
            "page_range": section.page_range if section else None,
            "coordinates": section.coordinates if section else [],
            "anchor_text": anchor_text[:240],
        },
        "part_ref": str(raw.get("part_ref") or infer_part_ref(section))[:120],
        "filled_by": normalize_filled_by(str(raw.get("filled_by") or "unknown")),
        "confidence": max(0.0, min(1.0, confidence)),
        "rationale": str(raw.get("rationale") or "LLM identified this as a reviewable template field.")[:500],
        "source_window": {
            "section_id": section.id if section else section_ref,
            "section_position": section.position if section else None,
            "field_index": index,
            "heading_path": section.heading_path if section else [],
            "extractor": "llm",
        },
        "review_status": "suggested",
    }


def is_low_value_template_label(label: str) -> bool:
    return normalize_space(label).lower() in {
        "the matters",
        "description",
        "reference",
        "date",
        "period",
        "number of days",
        "number of weeks",
    }


def clean_label_text(value: str) -> str:
    value = re.sub(r"\[[^\]]+\]", "", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"[_\\]+", " ", value)
    value = re.sub(r"\b(insert|subject to review by project office)\b", " ", value, flags=re.I)
    value = re.sub(r"\s*\([^)]*$", "", value)
    value = normalize_space(value).strip(" .:-;")
    return value


def dedupe_field_candidates(fields: list[dict[str, object]]) -> list[dict[str, object]]:
    seen_keys: set[str] = set()
    seen_labels: set[tuple[str, str]] = set()
    deduped = []
    for field in fields:
        key = str(field["field_key"])
        label_key = (
            str(field["template_doc"]),
            str(field.get("part_ref") or ""),
            normalize_space(str(field["label"])).lower(),
        )
        if key in seen_keys or label_key in seen_labels:
            continue
        seen_keys.add(key)
        seen_labels.add(label_key)
        deduped.append(field)
    return deduped


def infer_template_doc(name: str) -> str:
    upper = name.upper()
    if "CDP1" in upper or "PART 1" in upper or "PART ONE" in upper:
        return "CDP1"
    if "CDP2" in upper or "PART 2" in upper or "PART TWO" in upper:
        return "CDP2"
    if "FOT" in upper or "FORM OF TENDER" in upper:
        return "FOT"
    if "AOA" in upper or "ARTICLES" in upper:
        return "AOA"
    return "GENERIC"


def infer_part_ref(section: models.Section | None) -> str:
    if not section:
        return ""
    for item in section.heading_path or []:
        if item:
            return item[:120]
    return section.title[:120]


def infer_filled_by(template_doc: str, section: models.Section | None) -> str:
    text = f"{template_doc} {section.title if section else ''}".lower()
    if "cdp2" in text or "contractor" in text or "tenderer" in text:
        return "tenderer"
    if "cdp1" in text or "project office" in text or "employer" in text or "client" in text:
        return "project_office"
    return "unknown"


def normalize_filled_by(value: str) -> str:
    normalized = slugify(value)
    if normalized in {"project_office", "employer", "client"}:
        return "project_office"
    if normalized in {"tenderer", "contractor", "bidder"}:
        return "bidder"
    if normalized in {"system", "system_derived", "calculated", "derived"}:
        return "system_derived"
    return "unknown"


def normalize_input_type(value: str) -> str:
    normalized = slugify(value)
    allowed = {
        "text",
        "enum",
        "list",
        "date",
        "money",
        "money_text",
        "percentage",
        "table",
        "signature_block",
        "file_list",
        "checklist",
    }
    if normalized in allowed:
        return normalized
    if "percent" in normalized:
        return "percentage"
    if "signature" in normalized:
        return "signature_block"
    if "file" in normalized or "document" in normalized:
        return "file_list"
    return "text"


def infer_input_type(text: str) -> str:
    lower = text.lower()
    if "hk$" in lower or "price" in lower:
        return "money"
    if "date" in lower:
        return "date"
    if "option" in lower:
        return "enum"
    if "table" in lower or "|" in text:
        return "table"
    return "text"


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
