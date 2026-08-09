# NEC Rule Extraction Demo

![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Node](https://img.shields.io/badge/node-22%2B-green)
![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688)
![React](https://img.shields.io/badge/frontend-React%20%2B%20Vite-61DAFB)

A full-stack demo that turns Hong Kong public works NEC Practice Notes (and similar reference documents) into a structured, reviewable rule library — extracting evidence-backed rule cards and rule-logic trees from PDF source text.

## Status

Early-stage / experimental. This is not a production compliance tool. It currently focuses on ingesting reference documents, repairing their structure, extracting rules, and presenting them for subject-matter-expert (SME) review. Mapping reviewed rules onto tender/template documents for automated pass/fail compliance checking is a planned next phase — see [`prd.md`](./prd.md) for the full product story and current scope boundaries.

## How it works

1. Submit a public PDF URL for a reference document.
2. The backend sends it to the [MinerU](https://mineru.net) document-parsing API, polls for completion, and downloads the extracted Markdown, JSON, images, and tables.
3. MinerU's Markdown output is repaired into a readable section tree.
4. The reviewer compares the source PDF against the repaired Markdown side by side.
5. Rule extraction runs section-by-section using concurrent LLM calls against any OpenAI-compatible endpoint, saving successful rules incrementally so progress stays visible even if some windows fail.
6. Extracted rules are shown as editable rule cards and as a collapsible Rule Logic Review tree (section → rule → options → references → rule links), with unresolved references highlighted.
7. Everything — the MinerU request/response, repaired Markdown, LLM call logs, structured rules (JSON/CSV), rule logic (JSON), and the source PDF — can be exported.

## Features

- PDF import via public URL, parsed through the MinerU API; raw artifacts archived under `storage/documents/{document_id}/`
- Section-tree repair with side-by-side source PDF / Markdown review
- Runtime-configurable MinerU and LLM credentials (session-only, not persisted or exported)
- Concurrent, windowed LLM rule extraction with incremental saves and per-window logging
- Editable rule cards and a collapsible Rule Logic Review tree
- Full export of raw artifacts, repaired Markdown, LLM call logs, and structured rules

## Tech stack

- **Backend**: FastAPI, SQLAlchemy, Pydantic, PostgreSQL
- **Frontend**: React + TypeScript, Vite
- **Testing**: Pytest (backend), Vitest + Testing Library (frontend)
- **External services**: MinerU (document parsing), any OpenAI-compatible LLM endpoint (e.g. Volcengine Ark / Doubao)

## Requirements

- Python 3.9+
- Node 22+
- PostgreSQL reachable through `DATABASE_URL`
- A MinerU API token (`MINERU_API_TOKEN`)
- An OpenAI-compatible LLM API key (`LLM_API_KEY`) — Volcengine Ark / Doubao is the default provider in `.env.example`

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm install
```

Copy `.env.example` to `.env` and fill in `DATABASE_URL`, `MINERU_API_TOKEN`, and `LLM_API_KEY`.

## Run

Start the backend:

```bash
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Start the frontend:

```bash
npm run dev
```

Open `http://127.0.0.1:5173`.

## Checks

```bash
pytest          # backend tests
npm run build   # frontend build
npm test        # frontend tests
```

## Project structure

```
backend/app/
├── main.py               # FastAPI app and routes
├── config.py              # settings
├── runtime_config.py       # runtime MinerU/LLM configuration
├── models.py, schemas.py   # SQLAlchemy models & Pydantic schemas
└── services/
    ├── mineru.py            # MinerU API client
    ├── llm.py                # OpenAI-compatible LLM client
    ├── extraction.py         # section classification & rule extraction
    ├── markdown.py           # section-tree repair
    └── artifacts.py          # storage of MinerU artifacts
src/                       # React + TypeScript frontend (Vite)
tests/                     # pytest backend test suite
```
