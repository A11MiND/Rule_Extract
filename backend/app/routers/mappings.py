from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import KnowledgeItem as KnowledgeItemModel
from ..models import Mapping as MappingModel
from ..models import Rule as RuleModel
from ..schemas import MappingRead, MappingStats, MappingUpdate
from ..services.mapping import run_full_mapping

router = APIRouter(prefix="/api/mappings", tags=["mappings"])

# In-memory mapping state
_map_state: dict = {"status": "idle", "progress": ""}


@router.get("", response_model=list[MappingRead])
def list_mappings(
    template_section_id: str | None = Query(None),
    human_confirmed: bool | None = Query(None),
    min_confidence: float | None = Query(None, ge=0, le=1),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(MappingModel)
    if template_section_id:
        q = q.filter(MappingModel.template_section_id == template_section_id)
    if human_confirmed is not None:
        q = q.filter(MappingModel.human_confirmed == human_confirmed)
    if min_confidence is not None:
        q = q.filter(MappingModel.confidence >= min_confidence)
    q = q.order_by(MappingModel.confidence.desc())
    rows = q.offset(offset).limit(limit).all()

    # Enrich with titles
    result: list[MappingRead] = []
    for m in rows:
        ki_title = ""
        if m.knowledge_item_id:
            ki = db.query(KnowledgeItemModel).filter(KnowledgeItemModel.id == m.knowledge_item_id).first()
            if ki:
                ki_title = ki.title
        ts_title = ""
        if m.template_section_id:
            ts = db.query(KnowledgeItemModel).filter(KnowledgeItemModel.id == m.template_section_id).first()
            if ts:
                ts_title = ts.title
        rule_subject = None
        if m.rule_id:
            rule = db.query(RuleModel).filter(RuleModel.id == m.rule_id).first()
            if rule:
                rule_subject = rule.subject

        result.append(
            MappingRead(
                id=m.id,
                knowledge_item_id=m.knowledge_item_id or "",
                knowledge_item_title=ki_title,
                rule_id=m.rule_id,
                rule_subject=rule_subject,
                template_section_id=m.template_section_id,
                template_section_title=ts_title,
                mapping_type=m.mapping_type,
                confidence=m.confidence,
                rationale=m.rationale or "",
                human_confirmed=m.human_confirmed,
                human_decision=m.human_decision,
                created_at=m.created_at.isoformat() if m.created_at else None,
            )
        )
    return result


@router.get("/stats", response_model=MappingStats)
def get_mapping_stats(db: Session = Depends(get_db)):
    total = db.query(func.count(MappingModel.id)).scalar() or 0
    confirmed = (
        db.query(func.count(MappingModel.id))
        .filter(MappingModel.human_confirmed == True)
        .scalar()
        or 0
    )
    rejected = (
        db.query(func.count(MappingModel.id))
        .filter(MappingModel.human_decision == "rejected")
        .scalar()
        or 0
    )
    pending = total - confirmed - rejected
    return MappingStats(total=total, confirmed=confirmed, pending=pending, rejected=rejected)


@router.put("/{mapping_id}", response_model=MappingRead)
def update_mapping(
    mapping_id: str,
    payload: MappingUpdate,
    db: Session = Depends(get_db),
):
    m = db.query(MappingModel).filter(MappingModel.id == mapping_id).first()
    if m is None:
        raise HTTPException(status_code=404, detail="Mapping not found")
    m.human_confirmed = payload.human_confirmed
    m.human_decision = payload.human_decision
    if payload.confirmed_by:
        m.confirmed_by = payload.confirmed_by
    db.commit()
    db.refresh(m)

    ki_title = ""
    if m.knowledge_item_id:
        ki = db.query(KnowledgeItemModel).filter(KnowledgeItemModel.id == m.knowledge_item_id).first()
        if ki:
            ki_title = ki.title
    ts_title = ""
    if m.template_section_id:
        ts = db.query(KnowledgeItemModel).filter(KnowledgeItemModel.id == m.template_section_id).first()
        if ts:
            ts_title = ts.title

    return MappingRead(
        id=m.id,
        knowledge_item_id=m.knowledge_item_id or "",
        knowledge_item_title=ki_title,
        rule_id=m.rule_id,
        template_section_id=m.template_section_id,
        template_section_title=ts_title,
        mapping_type=m.mapping_type,
        confidence=m.confidence,
        rationale=m.rationale or "",
        human_confirmed=m.human_confirmed,
        human_decision=m.human_decision,
        created_at=m.created_at.isoformat() if m.created_at else None,
    )


@router.get("/section/{template_section_id}", response_model=list[MappingRead])
def get_section_mappings(
    template_section_id: str,
    db: Session = Depends(get_db),
):
    rows = (
        db.query(MappingModel)
        .filter(MappingModel.template_section_id == template_section_id)
        .order_by(MappingModel.confidence.desc())
        .all()
    )
    result: list[MappingRead] = []
    for m in rows:
        ki_title = ""
        if m.knowledge_item_id:
            ki = db.query(KnowledgeItemModel).filter(KnowledgeItemModel.id == m.knowledge_item_id).first()
            if ki:
                ki_title = ki.title
        ts_title = ""
        if m.template_section_id:
            ts = db.query(KnowledgeItemModel).filter(KnowledgeItemModel.id == m.template_section_id).first()
            if ts:
                ts_title = ts.title
        rule_subject = None
        if m.rule_id:
            rule = db.query(RuleModel).filter(RuleModel.id == m.rule_id).first()
            if rule:
                rule_subject = rule.subject

        result.append(
            MappingRead(
                id=m.id,
                knowledge_item_id=m.knowledge_item_id or "",
                knowledge_item_title=ki_title,
                rule_id=m.rule_id,
                rule_subject=rule_subject,
                template_section_id=m.template_section_id,
                template_section_title=ts_title,
                mapping_type=m.mapping_type,
                confidence=m.confidence,
                rationale=m.rationale or "",
                human_confirmed=m.human_confirmed,
                human_decision=m.human_decision,
                created_at=m.created_at.isoformat() if m.created_at else None,
            )
        )
    return result


def _run_mapping_task() -> None:
    """Background task: run auto-mapping."""
    global _map_state
    _map_state = {"status": "running", "progress": "Starting..."}

    from ..database import SessionLocal
    from ..runtime_config import effective_llm_key, get_runtime_config
    from ..services.llm import LLMClient

    db = SessionLocal()
    try:
        config = get_runtime_config()
        llm = LLMClient(
            api_base=config.llm_api_base,
            api_key=effective_llm_key(config),
            model=config.llm_model,
        )
        totals = run_full_mapping(db, llm)
        total = sum(totals.values())
        _map_state = {
            "status": "completed",
            "progress": f"Created {total} mappings: {totals}",
        }
    except Exception as exc:
        _map_state = {"status": "failed", "progress": str(exc)}
    finally:
        db.close()


@router.post("/auto-map")
def trigger_auto_map(background_tasks: BackgroundTasks):
    global _map_state
    if _map_state.get("status") == "running":
        return {"status": "already_running"}
    _map_state = {"status": "queued", "progress": "Queued..."}
    background_tasks.add_task(_run_mapping_task)
    return {"status": "queued"}


@router.get("/auto-map/status")
def get_map_status():
    return {"status": _map_state.get("status", "idle"), "progress": _map_state.get("progress", "")}
