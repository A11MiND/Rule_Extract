from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from ..models import KnowledgeItem as KnowledgeItemModel
from ..models import Mapping as MappingModel
from ..models import Rule as RuleModel
from .llm import LLMClient


# ──────────────────────────────────────────────
# System prompt — Rule → Section mapping
# ──────────────────────────────────────────────

RULE_TO_SECTION_SYSTEM = """\
Return JSON only: {"mappings": [...]}.

You match NEC Practice Notes rules to NEC tender template sections.

A rule APPLIES to a section if a tender reviewer would check that section against that rule
when vetting a submitted tender.

Input format:
- Template Section: title + content excerpt
- Rules list: rule_id | subject | condition | action

For each rule, decide if it applies to the given section. Be strict — only map if there's
a clear connection.

Output for each rule that applies:
{
  "rule_id": "rule-...",
  "applies": true,
  "confidence": 0.0-1.0,
  "rationale": "One sentence explaining the connection"
}

Do NOT map rules where the connection is speculative or tangential.
Only return mappings where applies=true."""


CLAUSE_TO_SECTION_SYSTEM = """\
Return JSON only: {"mappings": [...]}.

You match NEC General/Special Conditions of Tender clauses to NEC tender template sections.

A clause APPLIES to a section if the clause governs or constrains what goes in that section.

Input format:
- Template Section: title + content excerpt
- Clauses: clause_number | title | content excerpt

For each clause, decide if it applies to the given section. Be strict — only map if the
clause explicitly relates to the content or purpose of that section.

Some clauses directly name specific template sections (e.g., GCT 2(1)(g) mentions "Form of Tender").
These are high-confidence mappings.

Output for each clause that applies:
{
  "knowledge_item_id": "kb-...",
  "applies": true,
  "confidence": 0.0-1.0,
  "rationale": "One sentence explaining the connection"
}

Do NOT map clauses where the connection is speculative. Only return mappings where applies=true."""


# ──────────────────────────────────────────────
# Mapping engine
# ──────────────────────────────────────────────


def _chunk_rules(rules: list[RuleModel], max_per_batch: int = 80) -> list[list[RuleModel]]:
    """Split rules list into batches that fit LLM context."""
    batches: list[list[RuleModel]] = []
    for i in range(0, len(rules), max_per_batch):
        batches.append(rules[i : i + max_per_batch])
    return batches


def _format_rules_brief(rules: list[RuleModel]) -> str:
    """Format rules as a compact text block for LLM input."""
    lines: list[str] = []
    for r in rules:
        parts = [f"ID:{r.id} | Type:{r.type} | Subject:{r.subject}"]
        if r.condition:
            parts.append(f"Condition:{r.condition[:200]}")
        if r.action:
            parts.append(f"Action:{r.action[:200]}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _format_clauses_brief(clauses: list[KnowledgeItemModel]) -> str:
    """Format clause KB items for LLM input."""
    lines: list[str] = []
    for c in clauses:
        cn = c.clause_number or c.id
        title = c.title
        excerpt = c.content[:300].replace("\n", " ")
        lines.append(f"ID:{c.id} | {cn} | {title} | {excerpt}")
    return "\n".join(lines)


def auto_map_rules_to_sections(
    db: Session,
    rules: list[RuleModel],
    template_sections: list[KnowledgeItemModel],
    llm: LLMClient,
) -> int:
    """Map Practice Notes rules → template sections. Returns count of mappings created."""
    created = 0

    for section in template_sections:
        section_text = f"{section.title}\n{section.content[:500]}"
        rule_batches = _chunk_rules(rules, max_per_batch=60)

        for batch in rule_batches:
            rules_text = _format_rules_brief(batch)
            user_prompt = (
                f"Template Section:\n{section_text}\n\n"
                f"Rules to evaluate:\n{rules_text}"
            )

            try:
                result = llm.complete_json(RULE_TO_SECTION_SYSTEM, user_prompt)
            except Exception:
                continue

            for m in result.get("mappings", []):
                if not m.get("applies"):
                    continue
                rule_id = m.get("rule_id", "")
                confidence = float(m.get("confidence", 0.5))
                if confidence < 0.5:
                    continue

                mapping_id = f"map-{uuid.uuid4().hex[:12]}"
                existing = (
                    db.query(MappingModel)
                    .filter(
                        MappingModel.rule_id == rule_id,
                        MappingModel.template_section_id == section.id,
                    )
                    .first()
                )
                if existing:
                    if confidence > existing.confidence:
                        existing.confidence = confidence
                        existing.rationale = m.get("rationale", "")
                    continue

                db.add(
                    MappingModel(
                        id=mapping_id,
                        knowledge_item_id="",
                        rule_id=rule_id,
                        template_section_id=section.id,
                        mapping_type="rule_to_section",
                        confidence=confidence,
                        rationale=m.get("rationale", ""),
                    )
                )
                created += 1

    db.commit()
    return created


def auto_map_clauses_to_sections(
    db: Session,
    clauses: list[KnowledgeItemModel],
    template_sections: list[KnowledgeItemModel],
    llm: LLMClient,
) -> int:
    """Map GCT/SCT/NTT/ACC clauses → template sections. Returns count of mappings created."""
    created = 0

    for section in template_sections:
        section_text = f"{section.title}\n{section.content[:500]}"
        clause_batches = _chunk_rules(clauses, max_per_batch=50)

        for batch in clause_batches:
            clauses_text = _format_clauses_brief(batch)
            user_prompt = (
                f"Template Section:\n{section_text}\n\n"
                f"Clauses to evaluate:\n{clauses_text}"
            )

            try:
                result = llm.complete_json(CLAUSE_TO_SECTION_SYSTEM, user_prompt)
            except Exception:
                continue

            for m in result.get("mappings", []):
                if not m.get("applies"):
                    continue
                ki_id = m.get("knowledge_item_id", "")
                confidence = float(m.get("confidence", 0.5))
                if confidence < 0.5:
                    continue

                mapping_id = f"map-{uuid.uuid4().hex[:12]}"
                existing = (
                    db.query(MappingModel)
                    .filter(
                        MappingModel.knowledge_item_id == ki_id,
                        MappingModel.template_section_id == section.id,
                    )
                    .first()
                )
                if existing:
                    if confidence > existing.confidence:
                        existing.confidence = confidence
                        existing.rationale = m.get("rationale", "")
                    continue

                db.add(
                    MappingModel(
                        id=mapping_id,
                        knowledge_item_id=ki_id,
                        rule_id=None,
                        template_section_id=section.id,
                        mapping_type="clause_to_section",
                        confidence=confidence,
                        rationale=m.get("rationale", ""),
                    )
                )
                created += 1

    db.commit()
    return created


def run_full_mapping(
    db: Session,
    llm: LLMClient | None = None,
) -> dict[str, int]:
    """Run both M1 and M2 mapping. Returns counts by mapping type."""
    client = llm or LLMClient()
    totals: dict[str, int] = {}

    # Fetch all rules (from Practice Notes extraction — doc #7 is PN)
    rules = db.query(RuleModel).all()

    # Fetch template sections
    template_sections = (
        db.query(KnowledgeItemModel)
        .filter(KnowledgeItemModel.source_type == "template_spec")
        .filter(KnowledgeItemModel.is_active == True)
        .all()
    )

    # Fetch clauses
    clauses = (
        db.query(KnowledgeItemModel)
        .filter(KnowledgeItemModel.source_type == "clause")
        .filter(KnowledgeItemModel.is_active == True)
        .all()
    )

    if rules and template_sections:
        n = auto_map_rules_to_sections(db, rules, template_sections, client)
        totals["rule_to_section"] = n

    if clauses and template_sections:
        n = auto_map_clauses_to_sections(db, clauses, template_sections, client)
        totals["clause_to_section"] = n

    return totals
