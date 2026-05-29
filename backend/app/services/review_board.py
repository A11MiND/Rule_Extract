from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import VettingFinding as VettingFindingModel
from ..models import VettingRun as VettingRunModel
from .llm import LLMClient


REVIEW_BOARD_SYSTEM = """\
Return JSON only: {"executive_summary": "...", "risk_rating": "...", "findings_by_section": {...}, "critical_issues": [...], "recommendations": [...]}.

You are the Review Board for an NEC tender review. Below are findings from specialist reviewers.

Your job:
1. Remove duplicates — same issue found by multiple skills → keep the most specific one
2. Group findings by template section
3. Sort by severity within each section (critical → high → medium → low → info)
4. Write an executive summary (2-3 paragraphs)
5. Assign overall risk rating:
   - critical: any critical finding OR >5 high findings
   - high: 3-5 high findings
   - medium: <3 high findings, multiple medium
   - low: only low/info findings

Output format:
{
  "executive_summary": "2-3 paragraphs...",
  "risk_rating": "critical|high|medium|low",
  "findings_by_section": {
    "fot": {
      "summary": "Brief section summary",
      "findings": ["finding-id-1", "finding-id-2", ...]
    }
  },
  "critical_issues": ["Brief description of each critical issue"],
  "recommendations": ["Action item 1", "Action item 2"]
}

Be concise and actionable."""


def aggregate_findings(
    db: Session,
    run_id: str,
    llm: LLMClient | None = None,
) -> dict[str, Any]:
    """Run the Review Board on a completed vetting run. Returns the report dict."""
    client = llm or LLMClient()

    findings = (
        db.query(VettingFindingModel)
        .filter(VettingFindingModel.vetting_run_id == run_id)
        .all()
    )

    if not findings:
        return {
            "executive_summary": "No findings to report.",
            "risk_rating": "low",
            "findings_by_section": {},
            "critical_issues": [],
            "recommendations": [],
        }

    # Build findings summary for LLM
    findings_text = "\n\n".join(
        f"[{f.id}] Skill:{f.skill} | Section:{f.section_id} | "
        f"Severity:{f.severity} | Verdict:{f.verdict}\n"
        f"Title: {f.title}\nDetail: {f.detail[:500]}"
        for f in findings
    )

    try:
        report = client.complete_json(
            REVIEW_BOARD_SYSTEM,
            f"Tender review findings:\n\n{findings_text}",
        )
    except Exception:
        # Fallback: build report locally
        by_section: dict[str, list[str]] = {}
        critical = []
        for f in findings:
            by_section.setdefault(f.section_id, []).append(f.id)
            if f.severity == "critical":
                critical.append(f.title)

        sev_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for f in findings:
            sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1

        if sev_counts["critical"] > 0 or sev_counts["high"] > 5:
            risk = "critical"
        elif sev_counts["high"] >= 3:
            risk = "high"
        elif sev_counts["high"] > 0 or sev_counts["medium"] > 3:
            risk = "medium"
        else:
            risk = "low"

        report = {
            "executive_summary": (
                f"Automated review found {len(findings)} findings across "
                f"{len(by_section)} sections. "
                f"{sev_counts['critical']} critical, {sev_counts['high']} high, "
                f"{sev_counts['medium']} medium, {sev_counts['low']} low."
            ),
            "risk_rating": risk,
            "findings_by_section": {
                sid: {"summary": f"{len(ids)} findings", "findings": ids}
                for sid, ids in by_section.items()
            },
            "critical_issues": critical,
            "recommendations": ["Review all findings and confirm or dismiss each one."],
        }

    # Update run counts
    run = db.query(VettingRunModel).filter(VettingRunModel.id == run_id).first()
    if run:
        run.total_findings = len(findings)
        sev = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for f in findings:
            sev[f.severity] = sev.get(f.severity, 0) + 1
        run.critical_count = sev["critical"]
        run.high_count = sev["high"]
        run.medium_count = sev["medium"]
        run.low_count = sev["low"]
        db.commit()

    return report
