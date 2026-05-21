from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import models, schemas
from .config import settings
from .database import SessionLocal, get_db, init_db
from .services.artifacts import download_source_pdf, extract_zip, write_zip
from .services.extraction import classify_sections, extract_rules
from .services.llm import LLMClient, LLMError
from .services.markdown import build_section_tree, parse_markdown_sections, parse_mineru_content_sections
from .services.mineru import MinerUClient, MinerUError
from .runtime_config import (
    effective_llm_key,
    effective_mineru_token,
    get_runtime_config,
    public_runtime_config,
    update_runtime_config,
)


app = FastAPI(title="NEC Rule Extraction Demo")
app.mount("/storage", StaticFiles(directory=settings.storage_root), name="storage")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/runtime-config", response_model=schemas.RuntimeConfigRead)
def get_config() -> dict:
    return public_runtime_config()


@app.post("/api/runtime-config", response_model=schemas.RuntimeConfigRead)
def set_config(payload: schemas.RuntimeConfigUpdate) -> dict:
    config = update_runtime_config(**payload.model_dump(exclude_none=True))
    return public_runtime_config(config)


@app.post("/api/documents", response_model=schemas.DocumentRead)
def create_document(
    payload: schemas.DocumentCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> models.Document:
    if not effective_mineru_token():
        raise HTTPException(status_code=409, detail="MinerU API token is required before importing a PDF.")
    document = models.Document(
        name=payload.name,
        pdf_url=str(payload.pdf_url),
        contract_family=payload.contract_family,
        status="mineru_queued",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    background_tasks.add_task(run_mineru_pipeline, document.id)
    return document


@app.get("/api/documents", response_model=list[schemas.DocumentRead])
def list_documents(db: Session = Depends(get_db)) -> list[models.Document]:
    return db.query(models.Document).order_by(models.Document.created_at.desc(), models.Document.id.desc()).all()


@app.get("/api/documents/{document_id}", response_model=schemas.DocumentRead)
def get_document(document_id: int, db: Session = Depends(get_db)) -> models.Document:
    return require_document(db, document_id)


@app.get("/api/documents/{document_id}/outline", response_model=list[schemas.SectionRead])
def get_outline(document_id: int, db: Session = Depends(get_db)) -> list[schemas.SectionRead]:
    require_document(db, document_id)
    sections = (
        db.query(models.Section)
        .filter(models.Section.document_id == document_id)
        .order_by(models.Section.position)
        .all()
    )
    parsed = [
        schemas.SectionRead.model_validate(section).model_copy(update={"children": []})
        for section in sections
    ]
    return build_schema_tree(parsed)


@app.get("/api/documents/{document_id}/source-pdf")
def get_source_pdf(document_id: int, db: Session = Depends(get_db)) -> FileResponse:
    document = require_document(db, document_id)
    manifest = dict(document.artifact_manifest or {})
    candidates = []
    if manifest.get("source_pdf_path"):
        candidates.append(Path(str(manifest["source_pdf_path"])))
    candidates.extend(Path(path) for path in manifest.get("files", []) if str(path).lower().endswith(".pdf"))
    for path in candidates:
        if path.exists():
            return FileResponse(path, media_type="application/pdf", filename=f"document-{document_id}.pdf")

    try:
        path = download_source_pdf(document.id, document.pdf_url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Unable to load source PDF: {exc}") from exc

    document.artifact_manifest = {**manifest, "source_pdf_path": str(path)}
    db.commit()
    return FileResponse(path, media_type="application/pdf", filename=f"document-{document_id}.pdf")


@app.put("/api/documents/{document_id}/sections/{section_id}", response_model=schemas.SectionRead)
def update_section(
    document_id: int,
    section_id: str,
    payload: schemas.SectionUpdate,
    db: Session = Depends(get_db),
) -> models.Section:
    section = (
        db.query(models.Section)
        .filter(models.Section.document_id == document_id, models.Section.id == section_id)
        .first()
    )
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    section.content = payload.content
    db.commit()
    db.refresh(section)
    return section


@app.post("/api/documents/{document_id}/extract-rules", response_model=schemas.ExtractRulesResponse)
def extract_document_rules(
    document_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> schemas.ExtractRulesResponse:
    document = require_document(db, document_id)
    if not document.sections:
        raise HTTPException(status_code=409, detail="Document has no Markdown sections to extract from.")
    if not effective_llm_key():
        raise HTTPException(status_code=409, detail="LLM API key is required before extracting rules.")
    document.status = "rule_extraction_queued"
    document.error_message = None
    db.commit()
    background_tasks.add_task(run_rule_extraction_pipeline, document.id)
    return schemas.ExtractRulesResponse(
        document_id=document.id, status=document.status, rules_created=0
    )


@app.get("/api/documents/{document_id}/rules", response_model=list[schemas.RuleRead])
def list_rules(document_id: int, db: Session = Depends(get_db)) -> list[models.Rule]:
    require_document(db, document_id)
    return (
        db.query(models.Rule)
        .filter(models.Rule.document_id == document_id)
        .order_by(models.Rule.created_at, models.Rule.id)
        .all()
    )


@app.put("/api/rules/{rule_id}", response_model=schemas.RuleRead)
def update_rule(rule_id: str, payload: schemas.RuleUpdate, db: Session = Depends(get_db)) -> models.Rule:
    rule = db.query(models.Rule).filter(models.Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    data = payload.model_dump()
    for key, value in data.items():
        if key == "source" and hasattr(value, "model_dump"):
            value = value.model_dump()
        elif key in {"options", "dependencies"}:
            value = [item.model_dump() if hasattr(item, "model_dump") else item for item in value]
        setattr(rule, key, value)
    db.commit()
    db.refresh(rule)
    return rule


@app.get("/api/documents/{document_id}/rule-graph", response_model=schemas.RuleGraph)
def get_rule_graph(document_id: int, db: Session = Depends(get_db)) -> schemas.RuleGraph:
    rules = (
        db.query(models.Rule)
        .filter(models.Rule.document_id == document_id)
        .order_by(models.Rule.created_at, models.Rule.id)
        .all()
    )
    nodes = [
        schemas.GraphNode(
            id=rule.id,
            label=(rule.subject or rule.action or rule.id)[:80],
            type=rule.type,
            confidence=rule.confidence,
        )
        for rule in rules
    ]
    edges: list[schemas.GraphEdge] = []
    existing_ids = {rule.id for rule in rules}
    for rule in rules:
        for next_id in rule.next_rule_ids or []:
            if next_id in existing_ids:
                edges.append(schemas.GraphEdge(source=rule.id, target=next_id, label="next"))
        for dependency in rule.dependencies or []:
            target = dependency.get("rule_id")
            if target in existing_ids:
                edges.append(
                    schemas.GraphEdge(source=rule.id, target=target, label=dependency.get("type", "references"))
                )
        for option in rule.options or []:
            for next_id in option.get("next_rule_ids", []):
                if next_id in existing_ids:
                    label = f"option {option.get('label', '')}".strip()
                    edges.append(schemas.GraphEdge(source=rule.id, target=next_id, label=label))
    return schemas.RuleGraph(nodes=nodes, edges=edges)


@app.get("/api/documents/{document_id}/stats", response_model=schemas.DocumentStats)
def get_document_stats(document_id: int, db: Session = Depends(get_db)) -> schemas.DocumentStats:
    document = require_document(db, document_id)
    return compute_document_stats(document)


@app.get("/api/documents/{document_id}/exports/mineru-request")
def export_mineru_request(document_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    document = require_document(db, document_id)
    return download_json(
        document.artifact_manifest.get("mineru_request") or {},
        f"document-{document_id}-mineru-request.json",
    )


@app.get("/api/documents/{document_id}/exports/mineru-result")
def export_mineru_result(document_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    document = require_document(db, document_id)
    payload = {
        "task_id": document.mineru_task_id,
        "state": document.mineru_state,
        "zip_url": document.artifact_manifest.get("zip_url"),
        "artifact_manifest": redact_sensitive(document.artifact_manifest or {}),
    }
    return download_json(payload, f"document-{document_id}-mineru-result.json")


@app.get("/api/documents/{document_id}/exports/markdown")
def export_markdown(document_id: int, db: Session = Depends(get_db)) -> PlainTextResponse:
    document = require_document(db, document_id)
    markdown = repaired_markdown(document)
    headers = {"Content-Disposition": f'attachment; filename="document-{document_id}-repaired.md"'}
    return PlainTextResponse(markdown, media_type="text/markdown", headers=headers)


@app.get("/api/documents/{document_id}/exports/llm-windows")
def export_llm_windows(document_id: int, db: Session = Depends(get_db)) -> Response:
    document = require_document(db, document_id)
    path = document.artifact_manifest.get("llm_windows_path")
    if path and Path(path).exists():
        return FileResponse(
            path,
            media_type="application/x-ndjson",
            filename=f"document-{document_id}-llm-windows.jsonl",
        )
    return PlainTextResponse(
        "",
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="document-{document_id}-llm-windows.jsonl"'},
    )


@app.get("/api/documents/{document_id}/exports/rules-json")
def export_rules_json(document_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    document = require_document(db, document_id)
    rules = [
        schemas.RuleRead.model_validate(rule).model_dump(mode="json")
        for rule in sorted(document.rules, key=lambda rule: (rule.created_at, rule.id))
    ]
    return download_json({"document_id": document_id, "rules": rules}, f"document-{document_id}-rules.json")


@app.get("/api/documents/{document_id}/exports/rules-csv")
def export_rules_csv(document_id: int, db: Session = Depends(get_db)) -> Response:
    document = require_document(db, document_id)
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "id",
            "section_id",
            "type",
            "subject",
            "condition",
            "action",
            "confidence",
            "review_status",
            "evidence_text",
            "options",
            "dependencies",
        ],
    )
    writer.writeheader()
    for rule in sorted(document.rules, key=lambda rule: (rule.created_at, rule.id)):
        writer.writerow(
            {
                "id": rule.id,
                "section_id": rule.section_id or "",
                "type": rule.type,
                "subject": rule.subject,
                "condition": rule.condition,
                "action": rule.action,
                "confidence": rule.confidence,
                "review_status": rule.review_status,
                "evidence_text": (rule.source or {}).get("evidence_text", ""),
                "options": json.dumps(rule.options or [], ensure_ascii=False),
                "dependencies": json.dumps(rule.dependencies or [], ensure_ascii=False),
            }
        )
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="document-{document_id}-rules.csv"'},
    )


@app.get("/api/documents/{document_id}/exports/rule-graph")
def export_rule_graph(document_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    graph = get_rule_graph(document_id, db)
    return download_json(graph.model_dump(mode="json"), f"document-{document_id}-rule-graph.json")


def run_mineru_pipeline(document_id: int) -> None:
    db = SessionLocal()
    try:
        document = require_document(db, document_id)
        document.status = "mineru_submitting"
        db.commit()

        config = get_runtime_config()
        client = MinerUClient(
            api_base=config.mineru_api_base,
            token=effective_mineru_token(config),
            model_version=config.mineru_model_version,
        )
        mineru_request = {
            "url": document.pdf_url,
            "model_version": config.mineru_model_version,
            "endpoint": f"{client.api_base}/extract/task",
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
        document.artifact_manifest = {**(document.artifact_manifest or {}), "mineru_request": mineru_request}
        db.commit()
        task_id = client.submit_task(document.pdf_url)
        document.mineru_task_id = task_id
        document.status = "mineru_processing"
        db.commit()

        result = client.poll_until_done(task_id)
        document.mineru_state = result.state
        zip_content = client.download_zip(result.zip_url)
        zip_path = write_zip(document.id, zip_content)
        manifest = extract_zip(document.id, zip_path)
        markdown_path = manifest.get("markdown_path")
        if not markdown_path:
            raise MinerUError("MinerU zip did not contain a Markdown file.")

        document.zip_path = str(zip_path)
        document.markdown_path = markdown_path
        document.artifact_manifest = {
            **(document.artifact_manifest or {}),
            **manifest,
            "mineru_raw": result.raw,
            "zip_url": result.zip_url,
        }
        persist_sections_from_artifacts(
            db,
            document,
            markdown=Path(markdown_path).read_text(encoding="utf-8"),
            manifest=manifest,
        )
        document.status = "markdown_ready"
        db.commit()
    except (MinerUError, Exception) as exc:
        document = db.query(models.Document).filter(models.Document.id == document_id).first()
        if document:
            document.status = "mineru_failed"
            document.error_message = str(exc)
            db.commit()
    finally:
        db.close()


def run_rule_extraction_pipeline(document_id: int) -> None:
    db = SessionLocal()
    try:
        document = require_document(db, document_id)
        document.status = "classifying_sections"
        document.error_message = None
        db.commit()

        config = get_runtime_config()
        api_key = effective_llm_key(config)
        if not api_key:
            raise LLMError("LLM API key is required before extracting rules.")
        llm = LLMClient(
            api_base=config.llm_api_base,
            api_key=api_key,
            model=config.llm_model,
            provider=config.llm_provider,
        )
        classify_sections(db, document, llm, concurrency=config.llm_concurrency)
        document.status = "extracting_rules"
        db.commit()
        extract_rules(db, document, llm, concurrency=config.llm_concurrency)
    except (LLMError, Exception) as exc:
        document = db.query(models.Document).filter(models.Document.id == document_id).first()
        if document:
            document.status = "rule_extraction_failed"
            document.error_message = str(exc)
            db.commit()
    finally:
        db.close()


def persist_sections_from_artifacts(
    db: Session,
    document: models.Document,
    markdown: str,
    manifest: dict,
) -> None:
    db.query(models.Section).filter(models.Section.document_id == document.id).delete()
    parsed_sections = parse_sections_from_manifest(manifest) or parse_markdown_sections(markdown)
    for section in parsed_sections:
        db.add(
            models.Section(
                id=section.id,
                document_id=document.id,
                position=section.position,
                level=section.level,
                title=section.title,
                heading_path=section.heading_path,
                content=section.content,
            )
        )
    db.commit()


def persist_sections_from_markdown(db: Session, document: models.Document, markdown: str) -> None:
    persist_sections_from_artifacts(db, document, markdown=markdown, manifest={})


def parse_sections_from_manifest(manifest: dict) -> list | None:
    json_paths = manifest.get("json_paths") or []
    content_list_paths = [
        Path(path)
        for path in json_paths
        if Path(path).name.endswith("_content_list.json")
        and not Path(path).name.endswith("_content_list_v2.json")
    ]
    for path in content_list_paths:
        if path.exists():
            sections = parse_mineru_content_sections(path)
            if sections:
                return sections
    return None


def build_schema_tree(sections: list[schemas.SectionRead]) -> list[schemas.SectionRead]:
    by_id = {section.id: section for section in sections}
    parsed_like = []
    for section in sections:
        parsed_like.append(
            type(
                "TreeSection",
                (),
                {
                    "id": section.id,
                    "position": section.position,
                    "level": section.level,
                    "title": section.title,
                    "heading_path": section.heading_path,
                    "content": section.content,
                    "children": [],
                },
            )()
        )
    tree = build_section_tree(parsed_like)

    def hydrate(node: object) -> schemas.SectionRead:
        section = by_id[node.id]
        return section.model_copy(update={"children": [hydrate(child) for child in node.children]})

    return [hydrate(node) for node in tree]


def compute_document_stats(document: models.Document) -> schemas.DocumentStats:
    sections = list(document.sections or [])
    rules = list(document.rules or [])
    manifest = document.artifact_manifest or {}
    dependency_links = 0
    option_rules = 0
    for rule in rules:
        dependency_links += len(rule.dependencies or [])
        dependency_links += sum(len(option.get("referenced_sections", [])) for option in rule.options or [])
        if rule.type == "option" or rule.options:
            option_rules += 1
    return schemas.DocumentStats(
        total_sections=len(sections),
        classified_sections=sum(1 for section in sections if section.classification),
        candidate_sections=sum(
            1
            for section in sections
            if section.classification not in {None, "background", "table_only"} and section.content.strip()
        ),
        llm_windows_completed=int(manifest.get("llm_windows_completed") or 0),
        llm_windows_total=int(manifest.get("llm_windows_total") or 0),
        rules_extracted=len(rules),
        option_rules=option_rules,
        dependency_links=dependency_links,
        low_confidence_rules=sum(1 for rule in rules if rule.confidence < 0.65),
        reviewed_rules=sum(1 for rule in rules if rule.review_status == "reviewed"),
        draft_rules=sum(1 for rule in rules if rule.review_status == "draft"),
        rejected_rules=sum(1 for rule in rules if rule.review_status == "rejected"),
        partial_failures=int(manifest.get("llm_window_failures") or 0),
    )


def repaired_markdown(document: models.Document) -> str:
    lines: list[str] = [f"# {document.name}", ""]
    for section in sorted(document.sections, key=lambda item: item.position):
        lines.append(f"{'#' * min(section.level, 6)} {section.title}")
        if section.content.strip():
            lines.append("")
            lines.append(section.content.strip())
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def download_json(payload: dict | list, filename: str) -> JSONResponse:
    return JSONResponse(
        content=redact_sensitive(payload),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def redact_sensitive(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: ("***REDACTED***" if "key" in key.lower() or "token" in key.lower() else redact_sensitive(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value


def require_document(db: Session, document_id: int) -> models.Document:
    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document
