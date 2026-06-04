from __future__ import annotations

import json
import re
import uuid

from sqlalchemy.orm import Session

from .. import models
from ..runtime_config import effective_llm_key, get_runtime_config
from .llm import LLMClient, LLMError


MAPPING_SYSTEM_PROMPT = """\
You are vetting a Hong Kong NEC ECC tender template field against extracted Practice Note rules.
Pick the top 5 rules that the field should be checked against, ranked by relevance.

Return JSON only:
{"mappings": [{"rule_id": "<id>", "confidence": 0.0-1.0, "rationale": "..."}]}

Rules:
- Only use rule_ids from the candidate list. Never invent new ones.
- Be strict: only pick rules that genuinely apply to this field. Skip decorative matches.
- Confidence is your best estimate of how relevant the rule is for vetting this field (0.0-1.0).
- If no candidates are relevant, return {"mappings": []}.
"""


def suggest_field_rule_mappings(
    db: Session,
    collection_id: str,
    *,
    template_source_ids: list[str] | None = None,
    rule_source_ids: list[str] | None = None,
) -> dict[str, int]:
    template_source_ids = template_source_ids or []
    rule_source_ids = rule_source_ids or []
    fields = (
        db.query(models.TemplateField)
        .filter(
            models.TemplateField.collection_id == collection_id,
            models.TemplateField.review_status == "approved",
        )
    )
    if template_source_ids:
        fields = fields.filter(models.TemplateField.source_document_id.in_(template_source_ids))
    fields = fields.all()
    verified_sources = (
        db.query(models.SourceDocument)
        .filter(
            models.SourceDocument.collection_id == collection_id,
            models.SourceDocument.doc_type.in_(["rulebook", "reference_clause"]),
            models.SourceDocument.status == "rules_verified",
            models.SourceDocument.linked_document_id.isnot(None),
        )
    )
    if rule_source_ids:
        verified_sources = verified_sources.filter(models.SourceDocument.id.in_(rule_source_ids))
    verified_sources = verified_sources.all()
    verified_document_ids = [source.linked_document_id for source in verified_sources if source.linked_document_id]
    rules = (
        db.query(models.Rule)
        .filter(models.Rule.document_id.in_(verified_document_ids))
        .all()
        if verified_document_ids
        else []
    )
    created = 0
    for field in fields:
        candidates = pre_filter_candidates(field, rules, limit=30)
        if not candidates:
            continue
        ranked = llm_rank_mappings(field, candidates)
        for entry in ranked:
            rule_id = entry.get("rule_id")
            if not rule_id:
                continue
            rule = next((r for r in candidates if r.id == rule_id), None)
            if rule is None:
                continue
            confidence = float(entry.get("confidence", 0.0))
            if confidence < 0.35:
                continue
            existing = (
                db.query(models.FieldRuleMapping)
                .filter(
                    models.FieldRuleMapping.template_field_id == field.id,
                    models.FieldRuleMapping.rule_id == rule.id,
                )
                .first()
            )
            if existing:
                continue
            db.add(
                models.FieldRuleMapping(
                    id=f"frm-{uuid.uuid4().hex[:10]}",
                    collection_id=collection_id,
                    template_field_id=field.id,
                    rule_id=rule.id,
                    source_type="rule",
                    check_type=infer_check_type(field, rule),
                    applicability_condition=rule.condition or "",
                    confidence=min(max(confidence, 0.0), 0.95),
                    rationale=str(entry.get("rationale", ""))[:500],
                    review_status="suggested" if confidence >= 0.65 else "needs_edit",
                    review_notes="",
                )
            )
            created += 1
    db.commit()
    return {"fields": len(fields), "mappings_created": created}


def pre_filter_candidates(
    field: models.TemplateField, rules: list[models.Rule], limit: int = 20
) -> list[models.Rule]:
    """Narrow the rule book to a small candidate set for the LLM ranker.

    Uses a simple token-overlap heuristic so the LLM only sees a few dozen
    plausible candidates per field rather than the full rule book.
    """
    field_tokens: set[str] = set()
    for source in (field.field_key, field.label, field.anchor_text, field.extraction_hint):
        if not source:
            continue
        for token in re.split(r"\W+", source.lower()):
            if len(token) >= 4:
                field_tokens.add(token)
    if not field_tokens:
        return rules[:limit]
    scored: list[tuple[int, models.Rule]] = []
    for rule in rules:
        rule_text = f"{rule.subject} {rule.condition} {rule.action}".lower()
        hits = sum(1 for tok in field_tokens if tok in rule_text)
        if hits > 0:
            scored.append((hits, rule))
    if not scored:
        return rules[:limit]
    scored.sort(key=lambda item: (item[0], item[1].confidence or 0.0), reverse=True)
    return [rule for _, rule in scored[:limit]]


def llm_rank_mappings(field: models.TemplateField, candidates: list[models.Rule]) -> list[dict[str, object]]:
    if not candidates:
        return []
    config = get_runtime_config()
    client = LLMClient(
        api_base=config.llm_api_base,
        api_key=effective_llm_key(config),
        model=config.llm_model,
        provider=config.llm_provider,
    )
    candidates_payload = [
        {
            "rule_id": r.id,
            "subject": r.subject,
            "condition": r.condition,
            "action": r.action,
            "type": r.type,
            "confidence": r.confidence,
        }
        for r in candidates
    ]
    user_prompt = (
        "TEMPLATE FIELD:\n"
        f"- field_key: {field.field_key}\n"
        f"- label: {field.label}\n"
        f"- anchor_text: {field.anchor_text or '(none)'}\n"
        f"- extraction_hint: {field.extraction_hint or '(none)'}\n"
        f"- input_type: {field.input_type}\n"
        f"- required: {field.required}\n"
        f"- template_doc: {field.template_doc}\n\n"
        f"CANDIDATE RULES ({len(candidates)}):\n"
        f"{json.dumps(candidates_payload, ensure_ascii=False, indent=2)}\n\n"
        "Pick the top 5 most relevant rules."
    )
    try:
        response = client.complete_json(MAPPING_SYSTEM_PROMPT, user_prompt)
    except LLMError as exc:
        return [
            {
                "rule_id": None,
                "confidence": 0.0,
                "rationale": f"LLM ranking failed: {exc}",
            }
        ]
    raw_mappings = response.get("mappings")
    if not isinstance(raw_mappings, list):
        return []
    valid_ids = {r.id for r in candidates}
    cleaned: list[dict[str, object]] = []
    for item in raw_mappings:
        if not isinstance(item, dict):
            continue
        rule_id = item.get("rule_id")
        if rule_id not in valid_ids:
            continue
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        cleaned.append(
            {
                "rule_id": rule_id,
                "confidence": confidence,
                "rationale": str(item.get("rationale", ""))[:500],
            }
        )
    return cleaned


def infer_check_type(field: models.TemplateField, rule: models.Rule) -> str:
    text = f"{field.input_type} {field.field_key} {rule.subject} {rule.action}".lower()
    if any(term in text for term in ["main option", "fee percentage", "tendered total", "contract date"]):
        return "deterministic"
    if any(term in text for term in ["scope", "site information", "key person"]):
        return "hybrid"
    return "llm"
