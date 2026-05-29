from __future__ import annotations

import json
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any

from sqlalchemy.orm import Session

from ..models import KnowledgeItem as KnowledgeItemModel
from ..models import IngestionLog as IngestionLogModel
from .llm import LLMClient


# ──────────────────────────────────────────────
# System prompts for each source type
# ──────────────────────────────────────────────

CLAUSE_EXTRACT_SYSTEM = """\
Return JSON only: {"clauses": [...]}.

You parse NEC ECC General/Special Conditions of Tender clauses from markdown content.

The input is markdown from a PDF extraction. GCT/SCT/NTT/ACC clauses are usually in tables with
columns: Clause Number | Clause Text | Remarks/Guidelines.

For each clause you find, output:

{
  "clauses": [
    {
      "clause_number": "GCT 1",
      "title": "Definitions",
      "content": "Full clause text, reconstructed as flowing prose...",
      "remarks": "Remarks/guidelines text if present...",
      "category": "definitions|submission|pricing|legal|administrative"
    }
  ]
}

Rules:
- Split by clause number pattern (GCT \\d+, SCT \\d+, NTT \\d+, ACC [IVX]+:\\d+)
- Reconstruct fragmented table text into flowing prose
- Extract remarks/guidelines column text separately
- Assign category based on clause subject matter
- Skip navigation text, page headers, footers, table of contents
- Output empty array if no clauses found"""

TEMPLATE_EXTRACT_SYSTEM = """\
Return JSON only: {"sections": [...]}.

You parse NEC ECC tender template documents (CDP1, CDP2, FOT, Grand Summary, Scope, Preambles, AOA)
into structured section specifications.

Input is markdown from a PDF extraction. Identify each section and its key characteristics.

For each section you find, output:

{
  "sections": [
    {
      "section_number": "§1",
      "title": "Section title",
      "content": "Full section text...",
      "fields": [{"name": "field_name", "type": "text|currency|date|table|choice", "required": true}],
      "review_hints": "Any [Note to project office] or review annotations found..."
    }
  ]
}

Rules:
- Split by clear section headings (## heading, numbered sections)
- Identify [insert ...] and [subject to review] placeholders
- Categorize fields by data type
- Keep full section text in content
- Skip boilerplate headers, page numbers, table of contents"""

POLICY_EXTRACT_SYSTEM = """\
Return JSON only: {"circulars": [...]}.

You extract NEC-relevant policy requirements from Hong Kong government Technical Circulars.

Input is the full text of a technical circular.

Output:

{
  "circulars": [
    {
      "circular_number": "ETWB TC(W) No. 50/2002",
      "title": "Circular title",
      "issuing_body": "DEVB|ETWB|CEDD",
      "effective_date": "2002-05-01",
      "supersedes": "Previous circular if mentioned...",
      "key_requirements": "Summarised policy requirements relevant to NEC tender preparation..."
    }
  ]
}

Rules:
- Extract circular reference number and full title
- Identify issuing body and dates
- Summarise key requirements that affect tender preparation or contract management
- Focus on NEC-relevant content only
- Output empty array if no circular data found"""

DEPARTMENT_RULE_EXTRACT_SYSTEM = """\
Return JSON only: {"rules": [...]}.

You parse CEDD Project Administration Handbook (PAH) chapters into structured rule items.

Input is markdown from a PDF extraction of PAH Chapter 5 or Chapter 6.

Output:

{
  "rules": [
    {
      "section_ref": "§3.1",
      "title": "Section title",
      "content": "Full section text...",
      "nec_relevant": true,
      "relevance_rationale": "Brief explanation of NEC applicability..."
    }
  ]
}

Rules:
- Split by section reference numbers (§X.Y, Chapter X, Section X)
- Flag sections relevant to NEC tender preparation vs general administration
- Preserve full section text in content
- Note any cross-references to Practice Notes or DEVB circulars"""


# ──────────────────────────────────────────────
# Ingestion pipeline
# ──────────────────────────────────────────────

def _chunk_text(text: str, max_chars: int = 12000) -> list[str]:
    """Split text into chunks that fit within LLM context windows."""
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_chars and current:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


def _ingest_clauses(
    client: LLMClient,
    markdown: str,
    parent_doc: str,
    source_doc: str,
    source_url: str | None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    chunks = _chunk_text(markdown, max_chars=10000)
    for chunk in chunks:
        result = client.complete_json(CLAUSE_EXTRACT_SYSTEM, f"Extract clauses from:\n\n{chunk}")
        for clause in result.get("clauses", []):
            if not clause.get("clause_number") or not clause.get("content"):
                continue
            cn = clause["clause_number"].strip()
            items.append({
                "id": f"kb-{parent_doc.lower()}-{cn.lower().replace(' ', '-').replace(':', '')}" if parent_doc
                else f"kb-clause-{uuid.uuid4().hex[:8]}",
                "source_type": "clause",
                "source_document": source_doc,
                "source_url": source_url,
                "title": f"{cn} {clause.get('title', '')}".strip(),
                "content": clause["content"],
                "clause_number": cn,
                "clause_category": clause.get("category", ""),
                "parent_document": parent_doc,
                "clause_remarks": clause.get("remarks", ""),
                "summary": clause["content"][:300],
            })
    return items


def _ingest_templates(
    client: LLMClient,
    markdown: str,
    template_name: str,
    source_doc: str,
    source_url: str | None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    chunks = _chunk_text(markdown, max_chars=10000)
    for chunk in chunks:
        result = client.complete_json(TEMPLATE_EXTRACT_SYSTEM, f"Extract template sections from:\n\n{chunk}")
        for sec in result.get("sections", []):
            if not sec.get("title") or not sec.get("content"):
                continue
            sn = sec.get("section_number", "").strip()
            title = sec["title"].strip()
            items.append({
                "id": f"kb-tmpl-{template_name.lower()}-{sn.lower().replace(' ', '-').replace('§', 's')}" if sn
                else f"kb-tmpl-{uuid.uuid4().hex[:8]}",
                "source_type": "template_spec",
                "source_document": source_doc,
                "source_url": source_url,
                "title": f"{template_name} {sn} {title}".strip(),
                "content": sec["content"],
                "template_name": template_name,
                "section_number": sn,
                "field_definitions": json.dumps(sec.get("fields", []), ensure_ascii=False),
                "summary": sec["content"][:300],
                "metadata_json": {
                    "review_hints": sec.get("review_hints", ""),
                },
            })
    return items


def _ingest_policies(
    client: LLMClient,
    text: str,
    source_doc: str,
    source_url: str | None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    chunks = _chunk_text(text, max_chars=10000)
    for chunk in chunks:
        result = client.complete_json(POLICY_EXTRACT_SYSTEM, f"Extract policies from:\n\n{chunk}")
        for pol in result.get("circulars", []):
            if not pol.get("circular_number") or not pol.get("key_requirements"):
                continue
            cn = pol["circular_number"].strip()
            items.append({
                "id": f"kb-pol-{cn.lower().replace(' ', '-').replace('/', '-').replace('(', '').replace(')', '').replace('.', '')}",
                "source_type": "policy",
                "source_document": source_doc,
                "source_url": source_url,
                "title": f"{cn} {pol.get('title', '')}".strip(),
                "content": pol.get("key_requirements", ""),
                "circular_number": cn,
                "issuing_body": pol.get("issuing_body", ""),
                "effective_date": pol.get("effective_date", ""),
                "supersedes": pol.get("supersedes", ""),
                "summary": pol["key_requirements"][:300],
            })
    return items


def _ingest_department_rules(
    client: LLMClient,
    markdown: str,
    department: str,
    chapter: str,
    source_doc: str,
    source_url: str | None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    chunks = _chunk_text(markdown, max_chars=10000)
    for chunk in chunks:
        result = client.complete_json(DEPARTMENT_RULE_EXTRACT_SYSTEM, f"Extract department rules from {department} {chapter}:\n\n{chunk}")
        for rule in result.get("rules", []):
            if not rule.get("title") or not rule.get("content"):
                continue
            sr = rule.get("section_ref", "").strip()
            items.append({
                "id": f"kb-{department.lower()}-{chapter.lower()}-{sr.lower().replace(' ', '-').replace('§', 's')}" if sr
                else f"kb-dept-{uuid.uuid4().hex[:8]}",
                "source_type": "department_rule",
                "source_document": source_doc,
                "source_url": source_url,
                "title": f"{department} {chapter} {sr} {rule['title']}".strip(),
                "content": rule["content"],
                "department": department,
                "chapter": chapter,
                "section_ref": sr,
                "summary": rule["content"][:300],
                "metadata_json": {
                    "nec_relevant": rule.get("nec_relevant", False),
                    "relevance_rationale": rule.get("relevance_rationale", ""),
                },
            })
    return items


def run_ingestion_pipeline(
    db: Session,
    source_type: str,
    source_document: str,
    markdown_or_text: str,
    *,
    source_url: str | None = None,
    parent_document: str | None = None,
    template_name: str | None = None,
    department: str | None = None,
    chapter: str | None = None,
    llm_client: LLMClient | None = None,
) -> int:
    """Run ingestion for one source document. Returns count of items created/updated."""
    client = llm_client or LLMClient()

    if source_type == "clause":
        raw_items = _ingest_clauses(client, markdown_or_text, parent_document or "", source_document, source_url)
    elif source_type == "template_spec":
        raw_items = _ingest_templates(client, markdown_or_text, template_name or "", source_document, source_url)
    elif source_type == "policy":
        raw_items = _ingest_policies(client, markdown_or_text, source_document, source_url)
    elif source_type == "department_rule":
        raw_items = _ingest_department_rules(client, markdown_or_text, department or "", chapter or "", source_document, source_url)
    else:
        raise ValueError(f"Unknown source_type: {source_type}")

    created = 0
    updated = 0
    seen_ids: set[str] = set()
    for item_data in raw_items:
        item_id = item_data["id"]
        # Skip duplicates within the same batch
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        existing = db.query(KnowledgeItemModel).filter(KnowledgeItemModel.id == item_id).first()
        if existing:
            for key, val in item_data.items():
                if key not in ("id",):
                    setattr(existing, key, val)
            updated += 1
        else:
            db.add(KnowledgeItemModel(**item_data))
            created += 1
    db.commit()
    return created + updated


def run_full_ingestion(
    db: Session,
    llm_client: LLMClient | None = None,
    source_filter: str | None = None,
) -> dict[str, int]:
    """Run ingestion for ALL available source documents. Returns counts by source_type."""
    client = llm_client or LLMClient()
    totals: dict[str, int] = {}

    # Import here to avoid circular imports at module level
    import os

    # ── GCT (General Conditions of Tender) ──
    if not source_filter or source_filter == "GCT":
        gct_path = "/tmp/vetting-poc/standard-library/GCT_p1-15.md"
        if os.path.exists(gct_path):
            with open(gct_path) as f:
                md = f.read()
            n = run_ingestion_pipeline(
                db, "clause", "ECC HK GCT Complete Set Dec 2025", md,
                parent_document="GCT",
                source_url="https://www.devb.gov.hk/en/publications_and_press_releases/publications/standard_contract_documents/index.html",
                llm_client=client,
            )
            totals["GCT"] = n

    # ── CDP1 (Contract Data Part 1) ──
    if not source_filter or source_filter == "CDP1":
        cdp1_path = "/tmp/vetting-poc/templates/CDP1.md"
        if os.path.exists(cdp1_path):
            with open(cdp1_path) as f:
                md = f.read()
            n = run_ingestion_pipeline(
                db, "template_spec", "NEC ECC HK Option C Template CDP1", md,
                template_name="CDP1",
                source_url="https://www.devb.gov.hk/en/publications_and_press_releases/publications/standard_contract_documents/index.html",
                llm_client=client,
            )
            totals["CDP1"] = n

    # ── PAH Ch5 ──
    if not source_filter or source_filter == "PAH_Ch5":
        pah5_path = "/tmp/vetting-poc/pah/PAH_Ch5_p1-5.md"
        if os.path.exists(pah5_path):
            with open(pah5_path) as f:
                md = f.read()
            n = run_ingestion_pipeline(
                db, "department_rule", "CEDD PAH Chapter 5", md,
                department="CEDD", chapter="Ch5",
                source_url="https://www.cedd.gov.hk/eng/publications/PAH/index.html",
                llm_client=client,
            )
            totals["PAH_Ch5"] = n

    return totals
