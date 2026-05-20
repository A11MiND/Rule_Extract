# NEC Rule Extraction Demo

Local full-stack demo for extracting structured rule cards and rule flows from Hong Kong public works NEC Practice Notes.

## Requirements

- Python 3.9+
- Node 22+
- PostgreSQL reachable through `DATABASE_URL`
- Real MinerU token in `MINERU_API_TOKEN`
- Real Volcengine Ark / Doubao key in `LLM_API_KEY`

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm install
```

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
pytest
npm run build
npm test
```
