# Tender Vetting API

The Tender Vetting API supports URL-based document intake, conversion, human text confirmation, rule and field review, mapping, procedure-set approval, and audit history.

## Interactive Documentation

- Swagger UI: `/docs`
- ReDoc: `/redoc`
- OpenAPI schema: `/openapi.json`
- Health check: `GET /api/health`

The local frontend and API currently share one trusted demo workspace. Authentication and role-based authorization are intentionally deferred. UI mutations are recorded as `Demo User`; background processing events are recorded as `System`.

Service API keys are session-only. They are never returned by the runtime-configuration API or written into audit-event diffs.

## Core Entities

| Entity | Purpose |
| --- | --- |
| `DocumentCollection` | Workspace containing related source documents |
| `LibrarySlot` | Configurable required or optional source placeholder |
| `SourceDocument` | Document metadata and workflow state |
| `Document` | Conversion job and cached artifacts |
| `Section` | Editable converted Markdown section with stable ID |
| `Rule` | Reviewable rule extracted from a rule book |
| `TemplateField` | Canonical value/check requirement extracted from a template |
| `FieldRuleMapping` | Human-reviewed relationship between a field and a rule |
| `VettingProcedureSet` | Versioned, approvable set of source versions and mappings |
| `AuditEvent` | Compact redacted before/after mutation record |

## Workflow

1. List or configure library placeholders with `GET/POST/PATCH /api/library-slots`.
2. Import a public PDF URL with `POST /api/source-documents/import-url`.
3. Poll `GET /api/documents/{id}` while conversion is active.
4. Edit converted sections with `PATCH /api/documents/{id}/sections/{sectionId}`.
5. Confirm reviewed text with `POST /api/source-documents/{id}/confirm-text`.
6. Extract and review rules or fields according to the source role.
7. Select approved template and rule sources for `POST /api/mapping-runs`.
8. Review mapping suggestions and save a draft procedure set.
9. Approve the procedure set to freeze the version.

## Source Documents

### Import URL

`POST /api/source-documents/import-url`

```json
{
  "collection_id": "col-example",
  "slot_id": "slot-example",
  "name": "Contract Data Part One",
  "description": "Project-office tender template",
  "doc_type": "template",
  "pdf_url": "https://example.gov.hk/cdp1.pdf",
  "grouping_level": 3
}
```

The response contains the new `SourceDocument` and its `linked_document_id`. Import requires a configured MinerU token.

### Update Metadata

`PATCH /api/source-documents/{id}`

```json
{
  "name": "CDP1 - 2026 Edition",
  "description": "Approved project-office template",
  "doc_type": "template"
}
```

### Confirm Text

`POST /api/source-documents/{id}/confirm-text`

Confirmation requires converted sections. It sets `text_review_status=verified`, records `text_verified_at`, and stores a SHA-256 content fingerprint.

## Document Review

### Update Heading And Markdown

`PATCH /api/documents/{id}/sections/{sectionId}`

```json
{
  "title": "3 Time",
  "content": "The completion date is [insert date]."
}
```

Section IDs remain stable. When a heading changes, descendant heading paths are recalculated.

### PDF Preview

`GET /api/documents/{id}/pages/{page}/preview`

Returns a cached small PNG preview of the requested PDF page. `404` means the source PDF has not been cached; `501` means the preview dependency is unavailable.

## Rule And Field Review

- `POST /api/source-documents/{id}/rules/bulk-review`
- `POST /api/source-documents/{id}/fields/bulk-review`

Rule approval preserves rejected rules. Field approval preserves rejected fields.

```json
{ "review_status": "reviewed" }
```

```json
{ "field_ids": [], "review_status": "approved" }
```

An empty `field_ids` list on the document-scoped endpoint means every outstanding field for that source document.

## Mapping

### Generate Selected-Source Suggestions

`POST /api/mapping-runs`

```json
{
  "collection_id": "col-example",
  "template_source_ids": ["src-cdp1"],
  "rule_source_ids": ["src-nec-practice-notes", "src-acc"]
}
```

Only approved fields and verified rule sources from the selected documents are considered. Deterministic phrase/token filtering limits each field to a focused candidate set before LLM ranking.

### Mapping CRUD

- `POST /api/field-rule-mappings`
- `PUT /api/field-rule-mappings/{id}`
- `DELETE /api/field-rule-mappings/{id}`

Mappings support confidence, rationale, applicability condition, check type, review status, and reviewer notes.

## Procedure Sets

- `GET/POST /api/procedure-sets`
- `PATCH /api/procedure-sets/{id}`
- `POST /api/procedure-sets/{id}/approve`
- `POST /api/procedure-sets/{id}/clone`

Draft procedure sets are editable. Approval requires all included mappings to be approved and freezes the version. Updating an approved set returns `409`; clone it to create the next draft version.

## Dashboard And Audit

- `GET /api/dashboard-summary?collection_id={id}`
- `GET /api/audit-events?entity_type={type}&limit=100`

Audit events contain actor, action, entity, summary, timestamp, and compact before/after objects. Secrets, document bodies, and large artifacts are redacted.

## Statuses

Common document states:

`created`, `mineru_queued`, `mineru_processing`, `markdown_ready`, `rule_extraction_queued`, `extracting_rules`, `rules_extracted`, `fields_extracted`, `rules_verified`, `fields_verified`, `mineru_failed`, `rule_extraction_failed`.

Review states:

- Rules: `draft`, `reviewed`, `rejected`
- Fields and mappings: `suggested`, `approved`, `needs_edit`, `rejected`
- Procedure sets: `draft`, `approved`

## Errors

| HTTP status | Meaning |
| --- | --- |
| `404` | Entity or artifact not found |
| `409` | Workflow precondition failed, such as missing conversion or immutable approved procedure |
| `422` | Invalid request data |
| `501` | Optional local preview capability unavailable |

Error responses use FastAPI's standard shape:

```json
{ "detail": "Human-readable explanation" }
```
