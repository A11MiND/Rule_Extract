from __future__ import annotations

import re

from sqlalchemy.orm import Session

from .. import models


POC_TEMPLATE_FIELDS: dict[str, list[dict[str, object]]] = {
    "CDP1": [
        {"field_key": "cdp1.main_option", "label": "Selected main Option", "anchor_text": "clauses for main Option [insert selected main Option]", "input_type": "enum", "extraction_hint": "Find selected main Option in Contract Data Part one."},
        {"field_key": "cdp1.secondary_options", "label": "Selected secondary Options", "anchor_text": "secondary Options [insert selected secondary Options]", "input_type": "list", "extraction_hint": "Extract all secondary options such as X1, X2, X20."},
        {"field_key": "cdp1.site_information_refs", "label": "Site Information documents", "anchor_text": "The Site Information is in the following documents", "input_type": "file_list", "extraction_hint": "Extract Site Information references and check for improper disclaimers."},
        {"field_key": "cdp1.scope_documents", "label": "Scope documents", "anchor_text": "The Scope is in the following documents", "input_type": "file_list", "extraction_hint": "Extract Scope document list and nearby wording."},
        {"field_key": "cdp1.early_warning_matters", "label": "Early Warning Register matters", "anchor_text": "matters will be included in the Early Warning Register", "input_type": "list", "extraction_hint": "Extract listed early warning matters."},
        {"field_key": "cdp1.retention", "label": "Retention percentage and free amount", "anchor_text": "retention", "input_type": "table", "extraction_hint": "Extract retention percentage and retention free amount where present."},
        {"field_key": "cdp1.pain_gain_share", "label": "Pain/gain share percentages", "anchor_text": "Contractor's share percentages", "input_type": "table", "extraction_hint": "Extract share ranges and Contractor share percentages."},
    ],
    "CDP2": [
        {"field_key": "cdp2.contractor_identity", "label": "Contractor name and address", "anchor_text": "The Contractor is", "input_type": "text", "extraction_hint": "Extract contractor name and address."},
        {"field_key": "cdp2.key_persons", "label": "Key persons experience and responsibilities", "anchor_text": "key person", "input_type": "table", "extraction_hint": "Extract key person names, experience, job responsibilities, and NEC experience evidence."},
        {"field_key": "cdp2.early_warning_matters", "label": "Contractor Early Warning Register matters", "anchor_text": "matters will be included in the Early Warning Register", "input_type": "list", "extraction_hint": "Extract contractor-proposed early warning matters."},
        {"field_key": "cdp2.mandatory_prebid", "label": "Mandatory pre-bid subcontractor/supplier", "anchor_text": "Mandatory Pre-bidding", "input_type": "table", "extraction_hint": "Extract work item, subcontractor/supplier name, address, authorized person."},
        {"field_key": "cdp2.optional_prebid", "label": "Optional pre-bid subcontractor/supplier", "anchor_text": "Optional Pre-bidding", "input_type": "table", "extraction_hint": "Extract optional pre-bid subcontractor/supplier details."},
        {"field_key": "cdp2.fee_percentage", "label": "Fee percentage", "anchor_text": "fee percentage", "input_type": "percentage", "extraction_hint": "Extract fee percentage and compare with cap/minimum."},
    ],
    "FOT": [
        {"field_key": "fot.tendered_total_words", "label": "Tendered total of Prices in words", "anchor_text": "tendered total of the Prices", "input_type": "money_text", "extraction_hint": "Extract amount written in words."},
        {"field_key": "fot.tendered_total_figures", "label": "Tendered total of Prices in figures", "anchor_text": "HK$", "input_type": "money", "extraction_hint": "Extract HKD tendered total in figures."},
        {"field_key": "fot.tender_validity", "label": "Tender validity period", "anchor_text": "abide by this Tender for the period", "input_type": "duration", "extraction_hint": "Extract validity period, normally 90 days unless amended."},
        {"field_key": "fot.signing_information", "label": "Tenderer signing information", "anchor_text": "Signature", "input_type": "signature_block", "extraction_hint": "Extract signature, capacity, company name, witness and date."},
    ],
    "AOA": [
        {"field_key": "aoa.main_option", "label": "Articles main Option", "anchor_text": "main Option [insert main Option]", "input_type": "enum", "extraction_hint": "Extract main Option stated in Articles of Agreement."},
        {"field_key": "aoa.contract_date", "label": "Contract Date", "anchor_text": "contract came into existence on", "input_type": "date", "extraction_hint": "Extract Contract Date from Articles of Agreement."},
        {"field_key": "aoa.contract_documents", "label": "Contract document composition", "anchor_text": "The contract comprises", "input_type": "checklist", "extraction_hint": "Extract included contract documents."},
        {"field_key": "aoa.execution_block", "label": "Execution and signing block", "anchor_text": "SIGNED, SEALED and DELIVERED", "input_type": "signature_block", "extraction_hint": "Extract execution block type and signer information."},
    ],
}


def build_template_fields(source: models.SourceDocument, db: Session) -> list[dict[str, object]]:
    template_doc = infer_template_doc(source.name)
    defaults = POC_TEMPLATE_FIELDS.get(template_doc, [])
    fields = []
    for item in defaults:
        fields.append(
            {
                "collection_id": source.collection_id,
                "source_document_id": source.id,
                "template_doc": template_doc,
                "section_ref": None,
                "review_status": "suggested",
                **item,
            }
        )
    text_sections = []
    if source.linked_document_id:
        text_sections = (
            db.query(models.Section)
            .filter(models.Section.document_id == source.linked_document_id)
            .order_by(models.Section.position)
            .all()
        )
    fields.extend(discover_template_fields(source, template_doc, text_sections))
    if fields:
        return dedupe_field_candidates(fields)
    for idx, section in enumerate(text_sections[:120], start=1):
        text = f"{section.title}\n{section.content}"
        if "[insert" not in text.lower() and "____" not in text:
            continue
        key = slugify(f"{template_doc}.{section.title}")[:80] or f"{template_doc.lower()}.field_{idx}"
        fields.append(
            {
                "collection_id": source.collection_id,
                "source_document_id": source.id,
                "template_doc": template_doc,
                "field_key": key,
                "label": section.title[:160],
                "anchor_text": text[:300],
                "input_type": infer_input_type(text),
                "required": True,
                "section_ref": section.id,
                "extraction_hint": f"Extract value near: {section.title[:120]}",
                "review_status": "suggested",
            }
        )
    return fields


def discover_template_fields(
    source: models.SourceDocument,
    template_doc: str,
    sections: list[models.Section],
) -> list[dict[str, object]]:
    fields: list[dict[str, object]] = []
    for section in sections[:220]:
        text = normalize_space(f"{section.title}\n{section.content}")
        if not text:
            continue
        field_text = strip_markup_for_field_scan(text)
        placeholders = find_template_placeholders(field_text)
        for idx, placeholder in enumerate(placeholders[:18], start=1):
            label = infer_field_label(field_text, placeholder)
            if not label or is_low_value_template_label(label):
                continue
            fields.append(
                template_field_candidate(
                    source=source,
                    template_doc=template_doc,
                    section=section,
                    suffix=f"p{idx}-{slugify(label)[:42]}",
                    label=label,
                    anchor_text=extract_anchor_text(field_text, placeholder),
                    input_type=infer_input_type(f"{label} {placeholder}"),
                    extraction_hint=f"Extract the value for '{label}' near placeholder: {placeholder[:80]}",
                )
            )
        if has_reviewable_table(text):
            label = infer_table_label(text, section.title)
            fields.append(
                template_field_candidate(
                    source=source,
                    template_doc=template_doc,
                    section=section,
                    suffix=f"table-{slugify(label)[:42]}",
                    label=label,
                    anchor_text=extract_table_anchor(text),
                    input_type="table",
                    extraction_hint=f"Extract table values for '{label}' from section '{section.title}'.",
                )
            )
    return fields


def template_field_candidate(
    source: models.SourceDocument,
    template_doc: str,
    section: models.Section,
    suffix: str,
    label: str,
    anchor_text: str,
    input_type: str,
    extraction_hint: str,
) -> dict[str, object]:
    return {
        "collection_id": source.collection_id,
        "source_document_id": source.id,
        "template_doc": template_doc,
        "field_key": f"{template_doc.lower()}.derived.{section.position}.{suffix}",
        "label": label[:180],
        "anchor_text": anchor_text[:500],
        "input_type": input_type,
        "required": True,
        "section_ref": section.id,
        "extraction_hint": extraction_hint[:240],
        "review_status": "suggested",
    }


def find_template_placeholders(text: str) -> list[str]:
    matches: list[str] = []
    bracket_pattern = re.compile(r"\[[^\]]*(?:insert|subject to review|HK\\?\$|_{2,}|two weeks|one month|12 months|12 weeks|365 days)[^\]]*\]", re.I)
    for match in bracket_pattern.finditer(text):
        value = match.group(0)
        lower = value.lower()
        if "delete any row" in lower:
            continue
        matches.append(value)
    blank_pattern = re.compile(r"(?:HK\\?\$\s*)?_{2,}|\\_\s*\\_+")
    matches.extend(match.group(0) for match in blank_pattern.finditer(text))
    return dedupe_strings(matches)


def infer_field_label(text: str, placeholder: str) -> str:
    idx = text.find(placeholder)
    if idx < 0:
        idx = 0
    prefix = text[max(0, idx - 180):idx]
    suffix = text[idx + len(placeholder): idx + len(placeholder) + 80]
    context_label = label_from_context(prefix, placeholder)
    if context_label:
        return context_label
    placeholder_label = label_from_placeholder(placeholder, prefix)
    if placeholder_label:
        return placeholder_label
    sentence = split_context_sentence(prefix, suffix)
    cleaned = clean_label_text(sentence)
    if not cleaned or len(cleaned) < 6:
        cleaned = clean_label_text(placeholder.strip("[]").replace("insert", ""))
    cleaned = cleaned.replace("The ", "", 1) if cleaned.startswith("The ") else cleaned
    return cleaned[:160]


def label_from_context(prefix: str, placeholder: str) -> str:
    context = clean_label_text(split_context_sentence(prefix, ""))
    lower = context.lower()
    placeholder_lower = placeholder.lower()
    if "site information is in the following documents" in lower:
        return "Site Information document reference"
    if "scope is in the following documents" in lower:
        return "Scope document reference"
    if "boundaries of the site are shown" in lower or "drawing nos" in lower:
        return "Site boundary drawing numbers"
    if "working areas are" in lower:
        return "Working areas"
    if "tender closing date is" in lower:
        return "Tender closing date"
    if "starting date is" in lower:
        return "Starting date offset from Contract Date"
    if "period within which completion is certified" in lower:
        return "Completion certification period"
    if "first programme for acceptance" in lower:
        return "First programme submission period"
    if "revised programmes for acceptance" in lower:
        return "Revised programme submission interval"
    if "completion date for the whole of the works" in lower:
        return "Completion date after starting date"
    if "period within which the client takes over" in lower:
        return "Client take over period after Completion"
    if "establishment works" in lower:
        return "Establishment Works period"
    if "aftercare to old and valuable trees" in lower:
        return "Aftercare period for Old and Valuable Trees"
    if "quality policy statement and quality plan" in lower:
        return "Quality plan submission period"
    if "between completion of the whole of the works and the defects date" in lower:
        return "Defects date period after Completion"
    if "defect correction period" in lower and "description" in placeholder_lower:
        return "Optional defect correction item description"
    if "defect correction period" in lower and "number of weeks" in placeholder_lower:
        return "Optional defect correction period"
    if "defect correction period" in lower:
        return "Defect correction period"
    if "adjudicator nominating body" in lower:
        return "Adjudicator nominating body"
    if "self-employed" in lower and "appendix" in lower:
        return "Self-employed person insurance appendix"
    if "advanced payment" in lower and "instalments" in lower:
        return "Advanced payment repayment instalments"
    if "advanced payment" in lower:
        return "Advanced payment amount"
    if "retention percentage" in lower:
        return "Retention percentage"
    if "limit of amount retained" in lower:
        return "Retention amount limit"
    if "incentive schedule for key performance indicators" in lower:
        return "KPI incentive schedule appendix"
    if "time within which the project manager gives an instruction" in lower:
        return "Project Manager instruction period for section subject to excision"
    if "completion date for the section subject to excision" in lower:
        return "Completion date for section subject to excision"
    return ""


def label_from_placeholder(placeholder: str, prefix: str) -> str:
    lower_prefix = prefix.lower()
    raw = placeholder.strip("[]")
    if "insert" not in raw.lower():
        return ""
    value = re.sub(r"\binsert\b", "", raw, flags=re.I)
    value = re.sub(r"\b(state|as appropriate|by the project office|commonly used.*)$", "", value, flags=re.I)
    value = re.sub(r"\s*\(.*$", "", value)
    value = clean_label_text(value)
    generic_values = {"date", "period", "reference", "references", "details", "name", "number"}
    if value.lower() in generic_values:
        context = clean_label_text(split_context_sentence(prefix, ""))
        context = re.sub(r"^\d+(?:\.\d+)*\s+", "", context)
        if context and len(context) > 6:
            return context[:140]
    if "project manager is" in lower_prefix[-120:]:
        return "Project Manager post/name"
    if "supervisor is" in lower_prefix[-120:]:
        return "Supervisor post/name"
    if "address for electronic communications" in lower_prefix[-80:]:
        return "Address for electronic communications"
    if "address for communications" in lower_prefix[-80:]:
        return "Address for communications"
    if value.lower() == "brief description of the works":
        return "Works description"
    if value.lower() in {"drawing no", "drawing no."}:
        return "Site boundary drawing numbers"
    if 4 <= len(value) <= 90:
        return value
    return ""


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


def split_context_sentence(prefix: str, suffix: str) -> str:
    prefix_parts = re.split(r"(?<=[.!?])\s+|\n+|•\s+|- ", prefix)
    left = prefix_parts[-1] if prefix_parts else prefix
    suffix_parts = re.split(r"(?<=[.!?])\s+|\n+|•\s+|- ", suffix)
    right = suffix_parts[0] if suffix_parts else ""
    return f"{left} {right}"


def extract_anchor_text(text: str, placeholder: str) -> str:
    idx = text.find(placeholder)
    if idx < 0:
        return text[:500]
    return text[max(0, idx - 180): idx + len(placeholder) + 220]


def strip_markup_for_field_scan(text: str) -> str:
    text = re.sub(r"\[\[MINERU_TABLE_HTML\]\].*?\[\[/MINERU_TABLE_HTML\]\]", " ", text, flags=re.S)
    text = re.sub(r"\[\[MINERU_MEDIA[^\]]+\]\]", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return normalize_space(text)


def has_reviewable_table(text: str) -> bool:
    if "[[MINERU_TABLE_HTML]]" not in text and "<table" not in text:
        return False
    lower = text.lower()
    return any(token in lower for token in ["<td></td>", "insert", "____", "subject to review", "hk\\$", "key date", "share percentage"])


def infer_table_label(text: str, title: str) -> str:
    lower = text.lower()
    lower_title = title.lower()
    if "key dates and conditions" in lower:
        return "Key dates and conditions"
    if "access dates are" in lower or "part of the site" in lower and "access date" in lower:
        return "Site access dates"
    if "contractor’s share percentages" in lower or "contractor's share percentages" in lower:
        return "Contractor share percentages and share ranges"
    if "liabilities and insurance" in lower_title and "additional insurance" in lower:
        return "Additional insurance requirements"
    if "liabilities and insurance" in lower_title and "insurance table" in lower:
        return "Insurance table"
    if "sectional completion" in lower_title:
        return "Sectional completion dates"
    if "delay damages" in lower_title:
        return "Delay damages rates by section"
    lead = text.split("[[MINERU_TABLE_HTML]]", 1)[0]
    lead = re.sub(r"\[\[MINERU_MEDIA[^\]]+\]\]", "", lead)
    sentences = [normalize_space(part) for part in re.split(r"(?<=[.!?])\s+|\n+", lead) if normalize_space(part)]
    for sentence in reversed(sentences[-4:]):
        if len(sentence) > 8:
            return sentence[:150]
    return f"{title} table"


def extract_table_anchor(text: str) -> str:
    start = text.find("[[MINERU_TABLE_HTML]]")
    if start < 0:
        start = text.find("<table")
    if start < 0:
        return text[:500]
    return text[max(0, start - 220): start + 700]


def dedupe_field_candidates(fields: list[dict[str, object]]) -> list[dict[str, object]]:
    seen_keys: set[str] = set()
    seen_labels: set[tuple[str, str]] = set()
    deduped = []
    for field in fields:
        key = str(field["field_key"])
        label_key = (str(field["template_doc"]), normalize_space(str(field["label"])).lower())
        if key in seen_keys or label_key in seen_labels:
            continue
        seen_keys.add(key)
        seen_labels.add(label_key)
        deduped.append(field)
    return deduped


def dedupe_strings(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        key = normalize_space(value).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


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
