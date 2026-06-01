from __future__ import annotations

from .. import models
from ..runtime_config import get_runtime_config
from .llm import LLMClient, LLMError


def evaluate_result(
    field: models.TemplateField,
    mapping: models.FieldRuleMapping,
    evidence: models.TenderFieldEvidence | None,
    rule: models.Rule | None = None,
) -> tuple[str, str, str]:
    """LLM-evaluate whether the extracted evidence satisfies the mapped rule.

    Returns (result, severity, reason).
    """
    if field.required and (not evidence or not evidence.value.strip()):
        return (
            "fail",
            "high",
            f"Required field '{field.label}' has no extracted tender evidence.",
        )
    if not evidence or not evidence.value.strip():
        return (
            "not_applicable",
            "low",
            f"No tender evidence was found for optional field '{field.label}'.",
        )
    config = get_runtime_config()
    client = LLMClient(api_key=config.llm_api_key, model=config.llm_model)
    rule_subject = rule.subject if rule else "(no rule linked)"
    rule_condition = (rule.condition if rule else "") or "(none)"
    rule_action = (rule.action if rule else "") or "(none)"
    system_prompt = (
        "You check whether extracted tender evidence satisfies the rule that a template field was mapped to.\n\n"
        "Return JSON only:\n"
        '{"result": "pass"|"fail"|"needs_review"|"not_applicable", "severity": "high"|"medium"|"low", "reason": "..."}\n\n'
        "Decision guide:\n"
        "- pass: evidence clearly satisfies the rule.\n"
        "- fail: evidence clearly contradicts the rule, or a required field has no evidence.\n"
        "- needs_review: ambiguous, partial, or the evidence is from an unusual source.\n"
        "- not_applicable: optional field with no evidence (rare; usually caught before this call).\n"
        "Severity is how serious a failure would be if confirmed. The reason should be 1-2 sentences."
    )
    user_prompt = (
        "TEMPLATE FIELD:\n"
        f"- field_key: {field.field_key}\n"
        f"- label: {field.label}\n"
        f"- required: {field.required}\n"
        f"- input_type: {field.input_type}\n\n"
        "MAPPED RULE:\n"
        f"- subject: {rule_subject}\n"
        f"- condition: {rule_condition}\n"
        f"- action: {rule_action}\n\n"
        "EXTRACTED TENDER EVIDENCE:\n"
        f"- value: {evidence.value}\n"
        f"- raw_excerpt: {evidence.raw_text or '(none)'}\n"
        f"- confidence: {evidence.confidence}\n\n"
        "Decide whether the evidence satisfies the rule."
    )
    try:
        response = client.complete_json(system_prompt, user_prompt)
    except LLMError as exc:
        return "needs_review", "medium", f"LLM check failed: {exc}"
    result = str(response.get("result", "needs_review"))
    if result not in {"pass", "fail", "needs_review", "not_applicable"}:
        result = "needs_review"
    severity = str(response.get("severity", "medium"))
    if severity not in {"high", "medium", "low"}:
        severity = "medium"
    reason = str(response.get("reason", "")).strip()[:500]
    return result, severity, reason
