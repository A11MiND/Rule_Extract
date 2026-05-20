# NEC Practice Note Rule Extraction Demo PRD

## 1. Purpose

Build a demo web portal for extracting structured rules from Hong Kong public works NEC Practice Notes, including Engineering and Construction Contract (ECC) and Term Service Contract (TSC) documents.

The demo accepts a public PDF URL, sends it to MinerU for document parsing, lets the user verify and edit the returned Markdown, then uses Doubao through Volcengine Ark to extract structured rules and rule relationships.

## 2. Demo Goals

- Import NEC Practice Note PDF documents by URL.
- Use MinerU real API integration to convert PDFs into structured Markdown and JSON artifacts.
- Preserve document hierarchy so users can inspect and edit content by heading.
- Extract rule-like content from verified Markdown with a structured LLM pipeline.
- Display extracted rules as reviewable cards.
- Display rule dependencies, options, and next-step logic as a graph or list flow.

## 3. Out Of Scope

- Direct PDF file upload.
- Mock MinerU or mock LLM mode.
- Tender compliance pass/fail checking.
- Production authentication and multi-user access control.
- Full RAG search over the document corpus.

## 4. User Flow

1. User enters a document name, contract family, and public PDF URL.
2. Backend submits the URL to MinerU `POST /api/v4/extract/task`.
3. Backend polls MinerU until the task is complete.
4. Backend downloads the returned zip artifact and extracts Markdown plus JSON files.
5. UI renders the Markdown as an expandable heading outline.
6. User verifies and edits sections if needed.
7. User starts rule extraction.
8. Backend classifies sections, extracts rules by outline window, reconciles duplicates, and builds dependencies.
9. UI displays rule cards and a dependency or option flow.

## 5. Integrations

### MinerU

- API base: `MINERU_API_BASE`, default `https://mineru.net/api/v4`.
- Token: `MINERU_API_TOKEN`.
- Model version: `MINERU_MODEL_VERSION`, default `vlm`.
- Submit task with a public PDF URL.
- Poll the task endpoint until completion.
- Download the zip result and store raw artifacts under `storage/`.

### Doubao / Volcengine Ark

- API base: `LLM_API_BASE`, default `https://ark.cn-beijing.volces.com/api/v3`.
- Token: `LLM_API_KEY`.
- Model: `LLM_MODEL`, default `doubao-seed-2-0-pro-260215`.
- Use strict JSON prompts for classification, extraction, and reconciliation.

## 6. Rule Schema

Each extracted rule should include:

- `id`
- `document_id`
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

`source` should include heading path, section ID, page range when available, evidence text, and MinerU coordinate references when available.

Supported rule types:

- `obligation`
- `prohibition`
- `permission`
- `definition`
- `procedure`
- `deadline`
- `option`
- `checklist`
- `background`

## 7. Extraction Strategy

- Parse Markdown by headings into stable sections.
- Run a classification pass to identify background, definitions, rule candidates, and mixed sections.
- Extract rules per heading-bounded window instead of sending the entire document in one prompt.
- Include breadcrumb, nearby context, and global definitions in each extraction request.
- Reject unsupported inference and require evidence-backed JSON.
- Reconcile duplicate or split rules after extraction.
- Build rule dependency edges such as `requires`, `leads_to`, `alternative_to`, and `references`.

## 8. UI Requirements

- Import screen for PDF URL and contract family.
- Job progress screen showing MinerU and extraction status.
- Markdown review screen with collapsible headings and section-level editing.
- Rule review screen with editable rule cards.
- Rule graph or flow screen showing option paths and dependencies.
- Clear error states for missing credentials, invalid URLs, failed MinerU jobs, timeout, malformed LLM output, and partial extraction failure.

## 9. Technical Stack

- Frontend: React, Vite, TypeScript.
- Backend: FastAPI, Pydantic, SQLAlchemy.
- Database: PostgreSQL via `DATABASE_URL`.
- Artifact storage: local filesystem under `STORAGE_ROOT`.
- Real integrations only for MinerU and Doubao.

## 10. Acceptance Criteria

- Git repository is initialized in the workspace.
- This PRD is committed before implementation work.
- A user can paste a public PDF URL and create a document job.
- MinerU task submission and polling are implemented.
- MinerU zip artifacts are downloaded, unzipped, and indexed.
- Extracted Markdown is rendered as a collapsible outline and can be edited.
- Rule extraction produces structured rules with evidence and confidence.
- Rule cards and rule dependency or option flow render in the browser.
- Backend tests cover Markdown parsing, MinerU response handling, zip extraction, and rule schema validation.
- Frontend checks cover import, progress states, Markdown review, rule cards, and graph display.
