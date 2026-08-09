# NEC Rule Extraction Portal

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB)](https://www.python.org/)
[![Node](https://img.shields.io/badge/Node-22%2B-339933)](https://nodejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-Vite%20%2B%20TS-61DAFB)](https://react.dev/)

A full-stack demo that turns Hong Kong public works NEC Practice Notes into a structured, reviewable rule library — the audit-logic layer between reference documents and automated tender compliance checking.

## Why

RAG alone doesn't work for compliance checking: it only retrieves relevant text after a question is asked, and gives no guarantee that every required check ran or that a reviewer can audit why a result passed or failed. This project builds an intermediate layer instead:

```
reference text → structured rule → reviewed rule logic → mapped template field → compliance result
```

This repo covers the first half of that pipeline: turning reference PDFs into evidence-backed, human-reviewable rules. Mapping reviewed rules to tender/template fields for automated pass/fail results is a later product phase, not implemented here.

## Current scope

- Import reference PDFs by URL and parse them with the MinerU API (Markdown, JSON, images, tables, source artifacts).
- Repair MinerU's raw Markdown output into a readable section tree.
- Side-by-side view of the source PDF and repaired Markdown for review.
- Runtime-configurable MinerU and any OpenAI-compatible LLM endpoint.
- Section classification and rule extraction using concurrent LLM windows.
- Incremental rule saving so extraction progress is visible as it runs.

See [`prd.md`](./prd.md) for the full product spec.

## Tech stack

- **Backend** — FastAPI, PostgreSQL, MinerU API, OpenAI-compatible LLM client (tested against Volcengine Ark / Doubao)
- **Frontend** — React, TypeScript, Vite
- **Testing** — pytest (backend), Vitest (frontend)

## Requirements

- Python 3.9+
- Node 22+
- PostgreSQL reachable via `DATABASE_URL`
- A MinerU API token (`MINERU_API_TOKEN`)
- An OpenAI-compatible LLM API key (`LLM_API_KEY`) — developed against Volcengine Ark / Doubao

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm install
cp .env.example .env   # fill in DATABASE_URL, MINERU_API_TOKEN, LLM_API_KEY
```

## Run

Backend:

```bash
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```bash
npm run dev
```

Open `http://127.0.0.1:5173`.

## Tests

```bash
pytest
npm run build
npm test
```

## Status

This is a local demo/PoC, not a production deployment — there's no auth layer, and it expects a locally reachable Postgres instance and real third-party API credentials to do anything useful. No license has been added yet; treat the code as all-rights-reserved until one is.
