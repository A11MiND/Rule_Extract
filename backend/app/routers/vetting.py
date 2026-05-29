from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import VettingFinding as VettingFindingModel
from ..models import VettingRun as VettingRunModel
from ..schemas import (
    VettingFindingRead,
    VettingFindingUpdate,
    VettingFindingsParams,
    VettingRunRead,
    VettingRunListParams,
)

router = APIRouter(prefix="/api/vetting", tags=["vetting"])


def _run_to_read(run: VettingRunModel) -> VettingRunRead:
    return VettingRunRead(
        id=run.id,
        title=run.title,
        template_id=run.template_id,
        status=run.status,
        source_file_path=run.source_file_path,
        source_file_type=run.source_file_type,
        total_sections=run.total_sections,
        completed_sections=run.completed_sections,
        total_findings=run.total_findings,
        critical_count=run.critical_count,
        high_count=run.high_count,
        medium_count=run.medium_count,
        low_count=run.low_count,
        error_message=run.error_message,
        created_at=run.created_at.isoformat() if run.created_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )


def _finding_to_read(f: VettingFindingModel) -> VettingFindingRead:
    return VettingFindingRead(
        id=f.id,
        vetting_run_id=f.vetting_run_id,
        section_id=f.section_id,
        skill=f.skill,
        rule_id=f.rule_id,
        verdict=f.verdict,
        severity=f.severity,
        title=f.title,
        detail=f.detail,
        tender_excerpt=f.tender_excerpt,
        rule_excerpt=f.rule_excerpt,
        human_reviewed=f.human_reviewed,
        human_verdict=f.human_verdict,
        human_comment=f.human_comment,
        created_at=f.created_at.isoformat() if f.created_at else None,
    )


@router.post("/runs")
def create_vetting_run(
    title: str = "Untitled Run",
    template_id: str = "ECC_HK_OptionC_v2025",
    db: Session = Depends(get_db),
):
    run_id = f"vr-{uuid.uuid4().hex[:12]}"
    run = VettingRunModel(
        id=run_id,
        title=title,
        template_id=template_id,
        status="created",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return _run_to_read(run)


@router.get("/runs", response_model=list[VettingRunRead])
def list_vetting_runs(
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(VettingRunModel)
    if status:
        q = q.filter(VettingRunModel.status == status)
    q = q.order_by(VettingRunModel.created_at.desc())
    return [_run_to_read(r) for r in q.offset(offset).limit(limit).all()]


@router.get("/runs/{run_id}", response_model=VettingRunRead)
def get_vetting_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(VettingRunModel).filter(VettingRunModel.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Vetting run not found")
    return _run_to_read(run)


@router.post("/runs/{run_id}/start")
def start_vetting_run(
    run_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    run = db.query(VettingRunModel).filter(VettingRunModel.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Vetting run not found")
    if run.status in ("running", "aggregating"):
        return {"status": "already_running"}
    # Stub — full pipeline requires uploaded tender content
    return {"status": "not_implemented", "detail": "Upload tender file first"}


@router.get("/runs/{run_id}/findings", response_model=list[VettingFindingRead])
def list_findings(
    run_id: str,
    skill: str | None = Query(None),
    severity: str | None = Query(None),
    section_id: str | None = Query(None),
    verdict: str | None = Query(None),
    human_reviewed: bool | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    run = db.query(VettingRunModel).filter(VettingRunModel.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Vetting run not found")
    q = db.query(VettingFindingModel).filter(VettingFindingModel.vetting_run_id == run_id)
    if skill:
        q = q.filter(VettingFindingModel.skill == skill)
    if severity:
        q = q.filter(VettingFindingModel.severity.in_(severity.split(",")))
    if section_id:
        q = q.filter(VettingFindingModel.section_id == section_id)
    if verdict:
        q = q.filter(VettingFindingModel.verdict == verdict)
    if human_reviewed is not None:
        q = q.filter(VettingFindingModel.human_reviewed == human_reviewed)
    q = q.order_by(
        VettingFindingModel.severity,
        VettingFindingModel.skill,
    )
    return [_finding_to_read(f) for f in q.offset(offset).limit(limit).all()]


@router.put("/runs/{run_id}/findings/{finding_id}", response_model=VettingFindingRead)
def update_finding(
    run_id: str,
    finding_id: str,
    payload: VettingFindingUpdate,
    db: Session = Depends(get_db),
):
    f = (
        db.query(VettingFindingModel)
        .filter(
            VettingFindingModel.id == finding_id,
            VettingFindingModel.vetting_run_id == run_id,
        )
        .first()
    )
    if f is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    updates = payload.model_dump(exclude_unset=True)
    for key, val in updates.items():
        setattr(f, key, val)
    db.commit()
    db.refresh(f)
    return _finding_to_read(f)


@router.get("/runs/{run_id}/report")
def get_report(run_id: str, db: Session = Depends(get_db)):
    run = db.query(VettingRunModel).filter(VettingRunModel.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Vetting run not found")
    return {"run_id": run.id, "report": run.report_json or {}}


@router.delete("/runs/{run_id}")
def delete_vetting_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(VettingRunModel).filter(VettingRunModel.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Vetting run not found")
    db.delete(run)
    db.commit()
    return {"deleted": True}
