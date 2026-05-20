from __future__ import annotations

from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import models, schemas
from .database import SessionLocal, get_db, init_db
from .services.artifacts import extract_zip, write_zip
from .services.extraction import classify_sections, extract_rules
from .services.llm import DoubaoClient, LLMError
from .services.markdown import build_section_tree, parse_markdown_sections
from .services.mineru import MinerUClient, MinerUError


app = FastAPI(title="NEC Rule Extraction Demo")

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


@app.post("/api/documents", response_model=schemas.DocumentRead)
def create_document(
    payload: schemas.DocumentCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> models.Document:
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
def extract_document_rules(document_id: int, db: Session = Depends(get_db)) -> schemas.ExtractRulesResponse:
    document = require_document(db, document_id)
    if not document.sections:
        raise HTTPException(status_code=409, detail="Document has no Markdown sections to extract from.")
    try:
        document.status = "classifying_sections"
        db.commit()
        llm = DoubaoClient()
        classify_sections(db, document, llm)
        document.status = "extracting_rules"
        db.commit()
        rules_created = extract_rules(db, document, llm)
        return schemas.ExtractRulesResponse(
            document_id=document.id, status=document.status, rules_created=rules_created
        )
    except (LLMError, Exception) as exc:
        document.status = "rule_extraction_failed"
        document.error_message = str(exc)
        db.commit()
        if isinstance(exc, LLMError):
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        raise


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


def run_mineru_pipeline(document_id: int) -> None:
    db = SessionLocal()
    try:
        document = require_document(db, document_id)
        document.status = "mineru_submitting"
        db.commit()

        client = MinerUClient()
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
        document.artifact_manifest = {**manifest, "mineru_raw": result.raw, "zip_url": result.zip_url}
        persist_sections_from_markdown(db, document, Path(markdown_path).read_text(encoding="utf-8"))
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


def persist_sections_from_markdown(db: Session, document: models.Document, markdown: str) -> None:
    db.query(models.Section).filter(models.Section.document_id == document.id).delete()
    parsed_sections = parse_markdown_sections(markdown)
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


def require_document(db: Session, document_id: int) -> models.Document:
    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document
