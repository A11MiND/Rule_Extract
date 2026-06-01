# NEC Practice Note Rule Extraction Portal PRD

## 1. Purpose

Build a demo portal that turns Hong Kong public works NEC Practice Notes and similar reference books into a structured, reviewable rule library.

The portal is not yet a full tender compliance checker. Its current job is to process reference books, repair the MinerU output into readable document structure, extract evidence-backed rules, and show the extracted rule logic for SME review. The next product phase maps those reviewed rules to actual tender/template fields and produces pass/fail/needs-review audit results.

## 2. Product Story

There are two different document types:

- Reference books: NEC Practice Notes, standard clauses, circulars, libraries of standard amendments, and other authority documents. These define the audit basis.
- Tender/template documents: the project-specific tender book or structured client template being checked. These provide the evidence to verify.

RAG alone is not enough for compliance checking because RAG only retrieves relevant text after a question is asked. It does not guarantee that all required checks were executed, that option-specific paths were followed, or that the reviewer can audit why a result passed or failed.

Rule extraction creates an intermediate audit logic layer:

`reference text -> structured rule -> reviewed rule logic -> mapped template field -> compliance result`

## 3. Current Demo Scope

- Import public PDF URLs.
- Use the real MinerU API to extract Markdown, JSON, images, tables, and source PDF artifacts.
- Repair MinerU Markdown into a readable section tree.
- Show side-by-side source PDF and repaired Markdown for review.
- Configure MinerU and any OpenAI-compatible LLM at runtime.
- Classify sections and extract rules using concurrent LLM windows.
- Save rules incrementally so progress is visible.
- Display editable rule cards.
- Display Rule Logic Review as a collapsible tree:
  - Section
  - Rule
  - Options
  - References
  - Rule links
- Highlight unresolved references.
- Export MinerU request/result, repaired Markdown, LLM windows, rules JSON/CSV, rule logic JSON, and source PDF.

## 4. Explicit Non-Scope For Current Demo

- Direct local PDF upload.
- Mock MinerU or mock LLM mode.
- Production authentication or multi-user access control.
- Final tender compliance pass/fail workflow.
- Full corpus RAG search.
- Automatic legal interpretation without SME review.

## 5. Current User Flow

1. User configures MinerU and LLM credentials in the portal. Keys are session-only backend runtime config and are not exported.
2. User enters document name and public PDF URL.
3. Backend submits the PDF URL to MinerU.
4. Backend caches the source PDF, polls MinerU, downloads the zip, and extracts artifacts under `storage/`.
5. Backend builds repaired sections from MinerU content JSON or Markdown fallback.
6. UI auto-opens Document Review when Markdown is ready.
7. User verifies source PDF against repaired Markdown.
8. User starts rule extraction.
9. Backend classifies sections, extracts rules, saves successful rules incrementally, and logs every LLM window.
10. UI shows live progress, rule cards, and Rule Logic Review.

## 6. Integrations

### MinerU

- API base: `MINERU_API_BASE`, default `https://mineru.net/api/v4`.
- Token: `MINERU_API_TOKEN`, from runtime config or `.env` fallback.
- Model version: `MINERU_MODEL_VERSION`, default `vlm`.
- Submit task with public PDF URL.
- Poll task until complete.
- Download zip result.
- Store raw artifacts under `storage/documents/{document_id}/`.

### LLM Provider

- Generic OpenAI-compatible chat completions API.
- Runtime config fields:
  - provider label
  - API base
  - model
  - API key
  - concurrency, clamped to 1-20
- Doubao/Volcengine Ark is one provider option, not a hard-coded dependency.
- Payload should request strict JSON where supported.
- Failed windows are logged and do not erase successful rules.

## 7. Current Rule Schema

Current persisted rule fields:

- `id`
- `document_id`
- `section_id`
- `source`
- `subject`
- `condition`
- `action`
- `type`
- `actor`
- `target`
- `deadline`
- `options`
- `dependencies`
- `next_rule_ids`
- `confidence`
- `review_status`
- `notes`

`source` includes heading path, section ID, page range when available, evidence text, and MinerU coordinates when available.

Supported current rule types:

- `obligation`
- `prohibition`
- `permission`
- `definition`
- `procedure`
- `deadline`
- `option`
- `checklist`
- `background`

## 8. Required Rule Schema Upgrade

To support real tender/template checking, the rule schema should be extended beyond text extraction:

- `applicability`: when this rule should be applied.
- `evidence_requirements`: required tender/template fields, documents, clauses, or narrative evidence.
- `template_targets`: candidate template field IDs that this rule checks.
- `validation_method`: `deterministic`, `llm_judgement`, `hybrid`, or `manual_review`.
- `expected_value`: exact value, accepted range, allowed enum, required presence, or semantic requirement.
- `severity`: `mandatory`, `recommended`, `advisory`, or `background`.
- `jurisdiction_or_scope`: Hong Kong public works, NEC ECC, NEC TSC, project stage, or other scope flags.
- `references`: section references, clause references, circular references, and unresolved references.
- `exceptions`: explicit carve-outs or approval paths.
- `review_notes`: SME correction notes.
- `mapping_status`: `unmapped`, `suggested`, `reviewed`, or `rejected`.

Example upgraded rule:

```json
{
  "source": {"section_id": "A4.1.1.8", "evidence_text": "..."},
  "subject": "Site Information in tender documents",
  "condition": "When preparing tender documents",
  "action": "Project Offices should include as much relevant Site Information as possible",
  "type": "obligation",
  "severity": "recommended",
  "applicability": {
    "stage": "tender_preparation",
    "contract_forms": ["ECC", "TSC", "PSC"]
  },
  "evidence_requirements": [
    {"kind": "document_presence", "label": "geotechnical baseline report"},
    {"kind": "document_presence", "label": "site investigation records"},
    {"kind": "document_presence", "label": "existing utilities records"}
  ],
  "template_targets": ["site_information.documents"],
  "validation_method": "hybrid",
  "references": [{"section": "A6.3.1", "status": "resolved"}]
}
```

## 9. Rule Extraction Optimization Plan

### 9.1 Section Repair

MinerU Markdown can misclassify numbered paragraphs as large headings. The backend should continue repairing hierarchy from content JSON and visible section numbering:

- `1`
- `1.1`
- `1.1.1`
- `A4`
- `A4.1`
- `A4.1.1`
- `A4.1.1.1`

Images, tables, and HTML table fragments should be preserved as evidence blocks so the LLM can see table/chart text when extracting rules.

### 9.2 Deterministic Pre-Classification

Before calling the LLM, the backend should do fast local detection:

- Empty sections.
- Table-only sections.
- Contents pages.
- Pure background narrative.
- Obvious obligation/prohibition/procedure candidates based on modal verbs and NEC keywords.
- Detected references such as `A6.3.1` or `Section A4.1.1.8`.

Only ambiguous sections should require LLM classification. This reduces latency and cost.

### 9.3 Concurrent Classification

If LLM classification is used, it must be concurrent and observable:

- Approximately 12 sections per classification window.
- Respect runtime concurrency, capped at 20.
- Log payload, response, status, and failure.
- Apply heuristic fallback for failed windows.
- Keep progress visible in stats.

### 9.4 Extraction Windows

Extraction should remain section-tree based instead of fixed token chunks:

- Approximately 3 candidate sections per extraction window.
- Include parent heading context.
- Include previous and next sibling summaries.
- Include global definitions and abbreviations.
- Include detected references and resolved reference snippets when cheap.
- Include nearby table/chart text when it belongs to the section.
- Require strict JSON.
- Require evidence text copied from the provided context.
- Return no rule when text is purely background.

### 9.5 Structured Rule Prompt

The extraction prompt should ask for both current fields and future audit fields:

- subject
- condition
- action
- type
- actor
- target
- deadline
- severity
- applicability
- evidence requirements
- template target suggestions
- validation method
- options
- references
- exceptions
- confidence
- evidence text

This does not require all future fields to be persisted immediately, but the LLM window export should contain them so the schema can be upgraded safely.

### 9.6 Reconciliation Pass

The current implementation saves deduplicated rules by fingerprint. The next reconciliation layer should add:

- Merge duplicated rules across adjacent sections.
- Split compound rules into atomic rules.
- Resolve section references by section code.
- Create unresolved reference objects for missing targets.
- Resolve option paths into rule links where possible.
- Normalize actor names.
- Normalize template target suggestions against a controlled field registry.
- Mark low-confidence or unsupported mappings for SME review.

### 9.7 Quality Gates

Rules should not be considered review-ready unless:

- Source section ID exists.
- Evidence text exists.
- Rule type is valid.
- Condition/action are not just copied headings.
- Applicability is explicit or intentionally empty.
- Template mapping is either reviewed or marked as unmapped.
- Any unresolved references are visible.

## 10. Tender Template Mapping Plan

### 10.1 Template Field Registry

The system needs a canonical registry for tender/template fields. Each field should include:

- `field_id`
- `label`
- `description`
- `data_type`: string, number, enum, date, boolean, file, table, clause text, or narrative.
- `aliases`: terms likely used in tender documents.
- `source_locations`: template tab, section, clause, table, or uploaded file.
- `extraction_hints`: regex, labels, nearby terms, or examples.
- `normalization`: enum mapping, currency parsing, percentage parsing, date parsing.
- `validation_supported`: deterministic, LLM, hybrid, or manual.

Example registry items:

```json
[
  {
    "field_id": "contract.main_option",
    "label": "Main Option",
    "data_type": "enum",
    "aliases": ["main Option", "Option A", "Option B", "Option C", "Option D"],
    "validation_supported": "deterministic"
  },
  {
    "field_id": "site_information.documents",
    "label": "Site Information Documents",
    "data_type": "file_list",
    "aliases": ["Site Information", "geotechnical baseline report", "site investigation records"],
    "validation_supported": "hybrid"
  },
  {
    "field_id": "commercial.fee_percentage",
    "label": "Fee Percentage",
    "data_type": "percentage",
    "aliases": ["fee percentage", "fee %"],
    "validation_supported": "deterministic"
  }
]
```

### 10.2 Rule-To-Field Mapping

Each rule should map to one or more template targets:

- LLM suggests candidate `template_targets`.
- Deterministic matching validates suggestions against the field registry.
- SME can approve, reject, or remap.
- Approved mapping becomes part of the audit logic.

Mapping states:

- `unmapped`: rule extracted but not connected to a template field.
- `suggested`: model suggested a mapping.
- `reviewed`: SME accepted mapping.
- `rejected`: SME rejected mapping.

### 10.3 Tender Evidence Extraction

The next phase should ingest tender/template evidence:

- Structured spreadsheet/template fields.
- Uploaded tender PDF/Word files.
- Clause text.
- Tables.
- Appendices and attachments.

The evidence extraction layer should produce:

- `field_id`
- `value`
- `raw_text`
- `source_document`
- `page_or_section`
- `confidence`
- `extraction_method`

### 10.4 Compliance Checking

The compliance checker should operate on structured rules plus extracted evidence:

1. Determine applicable rules based on project context and template values.
2. Retrieve required evidence fields.
3. Run deterministic checks where possible.
4. Use LLM judgement only for semantic/narrative evidence.
5. Produce result:
   - `pass`
   - `fail`
   - `needs_review`
   - `not_applicable`
6. Return source citation from both rulebook and tender evidence.

Example output:

```json
{
  "rule_id": "rule-123",
  "template_field": "site_information.documents",
  "result": "needs_review",
  "reason": "Existing utilities records were not found in the submitted Site Information evidence.",
  "rule_source": "A4.1.1.8",
  "tender_evidence": ["Site Information appendix, page 12"]
}
```

## 11. Knowledge Base Role

There should be multiple knowledge layers:

- Rule library: structured rules extracted from reference books.
- Reference retrieval index: RAG index over source text for citations, explanations, and unresolved context.
- Tender evidence store: extracted template/tender values.
- External reference store: circulars, standard clauses, amendment libraries, and policy documents.

RAG should support retrieval and explanation. The actual audit decision should be driven by structured rules, mappings, and evidence checks.

## 12. UI Requirements

### Current UI

- Import PDF page with API config and PDF URL.
- Processing page with single progress bar and stats.
- Document Review page with source PDF and repaired Markdown side by side.
- Rules page with cards, filters, edit, and export.
- Rule Logic Review page with collapsible section/rule tree.
- History selector and New Work button.
- Workflow page for the rulebook-to-template-to-vetting POC:
  - `Library`: register rulebooks, reference clauses, templates, and tender submissions in one collection.
  - `Templates`: extract and review CDP1/CDP2/FOT/AOA template fields.
  - `Mappings`: generate suggested template-field-to-rule mappings and approve/reject them.
  - `Tender Vetting`: create a tender submission, extract field evidence, and run approved mapping checks.
  - `Results`: open and delete prior submission results.
  - `Settings`: create/delete collections and switch active scope.

### Implemented Mapping POC

The first implementation keeps the existing Practice Note rule extraction flow and adds a compatible workflow layer:

- `document_collections` isolate rulebooks, reference sources, templates, mappings, submissions, evidence, and results.
- `source_documents` registers each imported/linked PDF as `rulebook`, `reference_clause`, `template`, or `tender_submission`.
- `template_fields` stores CDP1/CDP2/FOT/AOA reviewable fields. The POC includes seeded NEC ECC HK fields for common CDP1/CDP2/FOT/AOA checks and can fall back to linked MinerU sections containing placeholders.
- `field_rule_mappings` stores LLM-suggested mappings from a template field to an existing rule. Suggested mappings are not audit-authoritative until a reviewer approves them.
- `mapping_runs` records each mapping run.
- `tender_submissions`, `tender_field_evidence`, and `check_results` store the tender review workflow.

Mapping suggestions use a two-stage pipeline: a lightweight keyword pre-filter narrows the rule book to ~20 candidate rules per field, then the LLM picks the top 5 with rationale and confidence:

`template field -> keyword pre-filter -> LLM rank top 5 -> suggested mappings -> SME approval`

Evidence extraction and vetting checks also call the LLM: each (field, tender section) pair returns a structured value, and each (field, mapped rule, evidence) triple returns pass/fail/needs_review with a reason. The current vetting check only executes approved mappings.

### Implemented Workflow APIs

- `POST /api/collections`
- `GET /api/collections`
- `DELETE /api/collections/{id}`
- `POST /api/source-documents`
- `GET /api/source-documents`
- `DELETE /api/source-documents/{id}`
- `POST /api/templates/{document_id}/extract-fields`
- `GET /api/template-fields`
- `PUT /api/template-fields/{id}`
- `DELETE /api/template-fields/{id}`
- `POST /api/mapping-runs`
- `GET /api/mapping-runs/{id}`
- `GET /api/field-rule-mappings`
- `PUT /api/field-rule-mappings/{id}`
- `POST /api/tender-submissions`
- `GET /api/tender-submissions`
- `POST /api/tender-submissions/{id}/extract-evidence`
- `POST /api/tender-submissions/{id}/run-checks`
- `GET /api/tender-submissions/{id}/results`
- `DELETE /api/tender-submissions/{id}`

### Future UI

- Rule Mapping page:
  - rule list
  - suggested template targets
  - SME approve/reject/remap
  - unresolved mapping filter
- Template Intake page:
  - upload/enter tender template
  - extracted fields table
  - field confidence review
- Compliance Check page:
  - applicable checks
  - pass/fail/needs-review results
  - rule citation
  - tender evidence citation
  - exportable audit report

## 13. Technical Stack

- Frontend: React, Vite, TypeScript.
- Backend: FastAPI, Pydantic, SQLAlchemy.
- Database: PostgreSQL via `DATABASE_URL`, with SQLite used for local demo.
- Artifact storage: local filesystem under `STORAGE_ROOT`.
- Integrations: MinerU and OpenAI-compatible LLM APIs.

## 14. Acceptance Criteria

### Current Demo

- Git repository is initialized and pushed to GitHub.
- User can paste a public PDF URL and create a document job.
- MinerU task submission and polling work.
- MinerU zip artifacts are downloaded, unzipped, and indexed.
- Source PDF renders inline in Document Review.
- Repaired Markdown preserves hierarchy, images, and tables.
- Section classification and rule extraction run concurrently.
- Rule extraction saves successful rules incrementally.
- Malformed or failed LLM windows are logged without deleting successful rules.
- Rule cards render and can be edited.
- Rule Logic Review renders section-to-rule-to-reference logic.
- Export endpoints do not include API keys or tokens.
- Backend tests pass.
- Frontend build passes.

### Next Phase

- Rule schema includes applicability, evidence requirements, template targets, validation method, severity, references, and mapping status.
- Template field registry exists.
- Rule-to-template mapping can be reviewed by SME.
- Tender/template evidence can be extracted into structured fields.
- Compliance check can produce pass/fail/needs-review/not-applicable with citations.
