from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import IngestionLog as IngestionLogModel
from ..models import KnowledgeItem as KnowledgeItemModel
from ..runtime_config import effective_llm_key, get_runtime_config
from ..schemas import (
    IngestResponse,
    IngestStatus,
    KnowledgeItemRead,
    KnowledgeItemStats,
    KnowledgeItemUpdate,
)
from ..services.embedding import embed_all_pending
from ..services.ingestion import run_full_ingestion

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

# In-memory ingestion state (simplest approach — survives reload but not restart)
_ingest_state: dict = {"status": "idle", "task_id": None, "progress": "", "errors": 0}


@router.get("", response_model=list[KnowledgeItemRead])
def list_knowledge_items(
    source_type: str | None = Query(None),
    parent_document: str | None = Query(None),
    template_name: str | None = Query(None),
    is_active: bool | None = Query(None),
    search: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(KnowledgeItemModel)
    if source_type:
        q = q.filter(KnowledgeItemModel.source_type == source_type)
    if parent_document:
        q = q.filter(KnowledgeItemModel.parent_document == parent_document)
    if template_name:
        q = q.filter(KnowledgeItemModel.template_name == template_name)
    if is_active is not None:
        q = q.filter(KnowledgeItemModel.is_active == is_active)
    if search:
        pattern = f"%{search}%"
        q = q.filter(
            KnowledgeItemModel.title.ilike(pattern)
            | KnowledgeItemModel.content.ilike(pattern)
        )
    q = q.order_by(KnowledgeItemModel.source_type, KnowledgeItemModel.title)
    return q.offset(offset).limit(limit).all()


@router.get("/stats", response_model=KnowledgeItemStats)
def get_knowledge_stats(db: Session = Depends(get_db)):
    rows = (
        db.query(
            KnowledgeItemModel.source_type,
            func.count(KnowledgeItemModel.id),
        )
        .group_by(KnowledgeItemModel.source_type)
        .all()
    )
    by_type: dict[str, int] = {st: cnt for st, cnt in rows}
    total = sum(by_type.values())
    active = (
        db.query(func.count(KnowledgeItemModel.id))
        .filter(KnowledgeItemModel.is_active == True)
        .scalar()
        or 0
    )
    return KnowledgeItemStats(
        total=total,
        active=active,
        inactive=total - active,
        by_type=by_type,
    )


@router.get("/{item_id}", response_model=KnowledgeItemRead)
def get_knowledge_item(item_id: str, db: Session = Depends(get_db)):
    item = db.query(KnowledgeItemModel).filter(KnowledgeItemModel.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    return item


@router.put("/{item_id}", response_model=KnowledgeItemRead)
def update_knowledge_item(
    item_id: str,
    payload: KnowledgeItemUpdate,
    db: Session = Depends(get_db),
):
    item = db.query(KnowledgeItemModel).filter(KnowledgeItemModel.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    updates = payload.model_dump(exclude_unset=True)
    for key, val in updates.items():
        setattr(item, key, val)
    db.commit()
    db.refresh(item)
    return item


def _run_ingestion_task(task_id: str) -> None:
    """Background task: run full ingestion pipeline then embed results."""
    global _ingest_state
    _ingest_state = {"status": "running", "task_id": task_id, "progress": "Starting...", "errors": 0}

    from ..database import SessionLocal
    from ..services.llm import LLMClient

    db = SessionLocal()
    try:
        log = IngestionLogModel(
            source_document="all",
            source_type="all",
            status="started",
        )
        db.add(log)
        db.commit()

        # Build LLM client with runtime-configured API key
        config = get_runtime_config()
        llm = LLMClient(
            api_base=config.llm_api_base,
            api_key=effective_llm_key(config),
            model=config.llm_model,
        )

        # Step 1: Ingest from source documents
        totals = run_full_ingestion(db, llm_client=llm)
        total_items = sum(totals.values())
        _ingest_state["progress"] = f"Ingested {total_items} items from {len(totals)} sources: {totals}"

        # Step 2: Embed all pending items
        n_embedded = embed_all_pending(db)
        _ingest_state["progress"] += f" | Embedded {n_embedded} items"

        log.status = "completed"
        log.items_created = total_items
        log.completed_at = datetime.now(timezone.utc)
        db.commit()

        _ingest_state = {
            "status": "completed",
            "task_id": task_id,
            "progress": f"Ingested {total_items} items, embedded {n_embedded}",
            "errors": 0,
        }
    except Exception as exc:
        import traceback
        _ingest_state = {
            "status": "failed",
            "task_id": task_id,
            "progress": str(exc),
            "errors": 1,
        }
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


@router.post("/ingest", response_model=IngestResponse)
def trigger_ingestion(background_tasks: BackgroundTasks):
    global _ingest_state
    if _ingest_state.get("status") == "running":
        return IngestResponse(status="already_running", task_id=_ingest_state.get("task_id"))
    task_id = uuid.uuid4().hex[:12]
    _ingest_state = {"status": "queued", "task_id": task_id, "progress": "Queued...", "errors": 0}
    background_tasks.add_task(_run_ingestion_task, task_id)
    return IngestResponse(status="queued", task_id=task_id)


@router.get("/ingest/status", response_model=IngestStatus)
def get_ingest_status():
    return IngestStatus(
        status=_ingest_state.get("status", "idle"),
        progress=_ingest_state.get("progress", "No ingestion run yet"),
        errors=_ingest_state.get("errors", 0),
    )


@router.post("/embed-all", response_model=dict)
def trigger_embed_all(db: Session = Depends(get_db)):
    n = embed_all_pending(db)
    return {"status": "ok", "embedded": n}
