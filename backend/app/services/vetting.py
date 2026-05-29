from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from sqlalchemy.orm import Session

from ..models import VettingFinding as VettingFindingModel
from ..models import VettingRun as VettingRunModel
from .llm import LLMClient
from .review_board import aggregate_findings


# ──────────────────────────────────────────────
# System prompts for each vetting skill
# ──────────────────────────────────────────────

V2_STRUCTURE_SYSTEM = """\
Return JSON only: {"findings": [...]}.

You are a document structure validator for NEC ECC tender submissions in Hong Kong public works.

Compare the submitted document structure against the expected template structure.
Flag: missing sections, extra sections, renamed sections, reordered sections.

Output for each issue:
{
  "section_id": "fot|cdp1|cdp2|bq|gs|scope|aoa|as|...",
  "verdict": "non_compliant",
  "severity": "critical|high|medium|low",
  "title": "Brief description",
  "detail": "Full explanation",
  "tender_excerpt": "What the tender shows"
}

If structure matches expected, return empty findings array."""

V3_COMPLETENESS_SYSTEM = """\
Return JSON only: {"findings": [...]}.

You check if all required fields in NEC tender template sections are properly filled.

Look for:
- [insert ...] placeholders that were not replaced
- Blank/missing values in mandatory fields
- Obviously dummy values (N/A, TBD, ---, xxx)
- Missing dates, signatures, or contract numbers

Output:
{
  "section_id": "string",
  "verdict": "non_compliant",
  "severity": "critical|high|medium|low",
  "title": "Brief description",
  "detail": "Full explanation including field name",
  "tender_excerpt": "The incomplete content"
}

Severity guide:
- critical: Missing mandatory fields that make the tender non-responsive
- high: Unreplaced placeholders in pricing or legal sections
- medium: Missing optional but important information
- low: Formatting inconsistencies"""

V4_COMPLIANCE_SYSTEM = """\
Return JSON only: {"findings": [...]}.

You check if submitted tender content complies with applicable NEC Practice Notes rules
and contract clauses. You are the COMPLIANCE CHECKER.

For each mapped rule/clause:
1. Read the rule requirement
2. Find the relevant tender content
3. Determine if compliant or not

Output:
{
  "section_id": "string",
  "rule_id": "rule-... or kb-...",
  "verdict": "compliant|non_compliant|cannot_verify",
  "severity": "critical|high|medium|low|info",
  "title": "One-line summary",
  "detail": "Full analysis comparing rule vs tender",
  "tender_excerpt": "Quote from tender",
  "rule_excerpt": "Quote from rule"
}

Be precise: quote both the rule text AND the specific tender text in your analysis."""

V5_CONSISTENCY_SYSTEM = """\
Return JSON only: {"findings": [...]}.

You cross-check values across ALL sections of an NEC tender submission for consistency.

Key checks:
- FOT tendered total = CDP2 total = Grand Summary grand total
- Contract number identical everywhere
- Project title consistent across all docs
- Dates logically consistent (closing > submission, completion > start)
- Option selections (A/B/C/D) match between CDP1 and pricing
- Company names/addresses match between FOT and CDP1

Output:
{
  "section_id": "primary_section",
  "verdict": "inconsistent|consistent",
  "severity": "critical|high|medium|low",
  "title": "Brief description",
  "detail": "What doesn't match and between which sections",
  "tender_excerpt": "The conflicting values"
}"""

V6_ARITHMETIC_SYSTEM = """\
Return JSON only: {"findings": [...]}.

You verify arithmetic correctness in NEC tender pricing documents.

Check:
- Qty × Rate = Amount for each line item
- All line items sum to section subtotal
- All section subtotals sum to grand total
- Contingency = stated% × subtotal
- Provisional sums correctly carried
- Share percentages sum correctly
- No cents in rounded amounts (HKD whole dollar)

Output:
{
  "section_id": "string",
  "verdict": "error|correct",
  "severity": "critical|high|medium|low",
  "title": "Brief description",
  "detail": "Expected X, got Y, discrepancy Z",
  "tender_excerpt": "The arithmetic you checked"
}"""

V7_POLICY_SYSTEM = """\
Return JSON only: {"findings": [...]}.

You check compliance with Hong Kong government technical circulars and department
rules applicable to NEC ECC tenders.

Check against:
- DEVB Technical Circulars (e.g., ETWB TC(W) requirements)
- CEDD Project Administration Handbook rules
- Any other applicable government policies

Output:
{
  "section_id": "string",
  "policy_id": "kb-pol-...",
  "verdict": "compliant|non_compliant|cannot_verify",
  "severity": "critical|high|medium|low",
  "title": "Brief description",
  "detail": "Policy requirement vs tender compliance",
  "rule_excerpt": "Quote from policy"
}"""


# ──────────────────────────────────────────────
# Skill execution
# ──────────────────────────────────────────────

SKILL_SYSTEMS: dict[str, str] = {
    "structure": V2_STRUCTURE_SYSTEM,
    "completeness": V3_COMPLETENESS_SYSTEM,
    "compliance": V4_COMPLIANCE_SYSTEM,
    "consistency": V5_CONSISTENCY_SYSTEM,
    "arithmetic": V6_ARITHMETIC_SYSTEM,
    "policy": V7_POLICY_SYSTEM,
}


def _run_single_skill(
    skill: str,
    section_id: str,
    section_content: str,
    all_sections: dict[str, str],
    mappings_json: str,
    policies_json: str,
    llm: LLMClient,
) -> list[dict[str, Any]]:
    """Execute one vetting skill on one section. Returns list of finding dicts."""
    system = SKILL_SYSTEMS.get(skill, V4_COMPLIANCE_SYSTEM)

    # Build user prompt based on skill type
    if skill == "structure":
        expected = "\n".join(f"- {sid}" for sid in all_sections)
        actual = "\n".join(f"- {sid}: {all_sections[sid][:100]}..." for sid in sorted(all_sections))
        user = f"Expected template sections:\n{expected}\n\nSubmitted tender sections:\n{actual}"
    elif skill == "completeness":
        user = f"Section: {section_id}\nContent:\n{section_content[:3000]}"
    elif skill in ("compliance", "policy"):
        user = (
            f"Section: {section_id}\n"
            f"Mapped requirements:\n{mappings_json}\n\n"
            f"Tender content:\n{section_content[:3000]}"
        )
    elif skill == "consistency":
        parts = [f"=== {sid} ===\n{all_sections.get(sid, 'N/A')[:1500]}" for sid in sorted(all_sections)]
        user = "Cross-check consistency across:\n\n" + "\n\n".join(parts)
    elif skill == "arithmetic":
        user = f"Section: {section_id}\nPricing content:\n{section_content[:3000]}"
    else:
        user = f"Section: {section_id}\n{section_content[:3000]}"

    try:
        result = llm.complete_json(system, user)
        return result.get("findings", [])
    except Exception:
        return []


def run_vetting_section(
    db: Session,
    run_id: str,
    section_id: str,
    section_content: str,
    all_sections: dict[str, str],
    mappings_for_section: list[dict[str, Any]],
    llm: LLMClient,
    concurrency: int = 6,
) -> int:
    """Run all 6 skills on one section in parallel. Returns count of findings created."""
    mappings_json = json.dumps(
        [{"rule_id": m.get("rule_id", ""), "content": m.get("rule_content", "")} for m in mappings_for_section],
        ensure_ascii=False,
    )
    policies_json = json.dumps(
        [{"policy_id": m.get("policy_id", ""), "content": m.get("policy_content", "")} for m in mappings_for_section],
        ensure_ascii=False,
    )

    all_findings: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures: dict[str, Any] = {}
        for skill in SKILL_SYSTEMS:
            f = executor.submit(
                _run_single_skill,
                skill,
                section_id,
                section_content,
                all_sections,
                mappings_json,
                policies_json,
                llm,
            )
            futures[f] = skill

        for future in as_completed(futures):
            skill = futures[future]
            try:
                findings = future.result()
                for finding in findings:
                    finding["skill"] = skill
                    finding.setdefault("section_id", section_id)
                    finding.setdefault("verdict", "non_compliant")
                    finding.setdefault("severity", "medium")
                    finding.setdefault("title", "")
                    finding.setdefault("detail", "")
                all_findings.extend(findings)
            except Exception:
                pass

    created = 0
    for fdata in all_findings:
        finding_id = f"vf-{uuid.uuid4().hex[:12]}"
        db.add(
            VettingFindingModel(
                id=finding_id,
                vetting_run_id=run_id,
                section_id=fdata.get("section_id", section_id),
                skill=fdata.get("skill", "compliance"),
                rule_id=fdata.get("rule_id"),
                verdict=fdata.get("verdict", "non_compliant"),
                severity=fdata.get("severity", "medium"),
                title=fdata.get("title", ""),
                detail=fdata.get("detail", ""),
                tender_excerpt=fdata.get("tender_excerpt"),
                rule_excerpt=fdata.get("rule_excerpt"),
            )
        )
        created += 1

    db.commit()
    return created


def run_vetting_pipeline(
    db: Session,
    run_id: str,
    sections: dict[str, str],
    mappings: dict[str, list[dict[str, Any]]],
    llm: LLMClient | None = None,
    concurrency: int = 6,
) -> int:
    """Run the full vetting pipeline on all sections. Returns total findings count."""
    client = llm or LLMClient()
    total_findings = 0
    completed = 0
    total_sections = len(sections)

    # Update run status
    run = db.query(VettingRunModel).filter(VettingRunModel.id == run_id).first()
    if run:
        run.status = "running"
        run.total_sections = total_sections
        db.commit()

    for section_id, content in sections.items():
        section_mappings = mappings.get(section_id, [])
        n = run_vetting_section(
            db, run_id, section_id, content, sections, section_mappings, client, concurrency
        )
        total_findings += n
        completed += 1

        if run:
            run.completed_sections = completed
            db.commit()

    # Aggregate findings with Review Board
    if run:
        run.status = "aggregating"
        db.commit()
        # Run Review Board
        aggregate_result = aggregate_findings(db, run_id, client)
        run.report_json = aggregate_result
        run.status = "completed"
        db.commit()

    return total_findings
