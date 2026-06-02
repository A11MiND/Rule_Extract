from __future__ import annotations

import uuid
import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..config import settings
from ..database import get_db
from ..runtime_config import get_runtime_config
from ..services.llm_check import evaluate_result
from ..services.llm_evidence import extract_evidence_value
from ..services.llm_mapping import suggest_field_rule_mappings
from ..services.template_parser import (
    build_template_fields,
    infer_template_doc,
)

router = APIRouter(prefix="/api", tags=["workflow"])


@router.post("/collections", response_model=schemas.CollectionRead)
def create_collection(payload: schemas.CollectionCreate, db: Session = Depends(get_db)):
    collection = models.DocumentCollection(id=f"col-{uuid.uuid4().hex[:10]}", **payload.model_dump())
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return collection


@router.get("/collections", response_model=list[schemas.CollectionRead])
def list_collections(db: Session = Depends(get_db)):
    return db.query(models.DocumentCollection).order_by(models.DocumentCollection.created_at.desc()).all()


@router.delete("/collections/{collection_id}")
def delete_collection(collection_id: str, db: Session = Depends(get_db)):
    collection = require_collection(db, collection_id)
    db.delete(collection)
    db.commit()
    return {"deleted": True}


@router.post("/source-documents", response_model=schemas.SourceDocumentRead)
def create_source_document(payload: schemas.SourceDocumentCreate, db: Session = Depends(get_db)):
    require_collection(db, payload.collection_id)
    source = models.SourceDocument(
        id=f"src-{uuid.uuid4().hex[:10]}",
        status="created",
        mineru_artifacts={},
        **payload.model_dump(),
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.get("/source-documents", response_model=list[schemas.SourceDocumentRead])
def list_source_documents(
    collection_id: str | None = Query(None),
    doc_type: str | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(models.SourceDocument)
    if collection_id:
        query = query.filter(models.SourceDocument.collection_id == collection_id)
    if doc_type:
        query = query.filter(models.SourceDocument.doc_type == doc_type)
    return query.order_by(models.SourceDocument.created_at.desc()).all()


@router.delete("/source-documents/{source_document_id}")
def delete_source_document(source_document_id: str, db: Session = Depends(get_db)):
    source = require_source_document(db, source_document_id)
    linked_document_id = source.linked_document_id
    linked_document = (
        db.query(models.Document).filter(models.Document.id == linked_document_id).first()
        if linked_document_id
        else None
    )
    source_count_for_linked_document = (
        db.query(models.SourceDocument)
        .filter(
            models.SourceDocument.linked_document_id == linked_document_id,
            models.SourceDocument.id != source.id,
        )
        .count()
        if linked_document_id
        else 0
    )

    document_dir = None
    if linked_document and source_count_for_linked_document == 0:
        rule_ids = [rule.id for rule in linked_document.rules]
        if rule_ids:
            db.query(models.FieldRuleMapping).filter(models.FieldRuleMapping.rule_id.in_(rule_ids)).delete(
                synchronize_session=False
            )
        document_dir = settings.storage_root / "documents" / str(linked_document.id)
        db.delete(linked_document)

    db.delete(source)
    db.commit()
    if document_dir and document_dir.exists():
        shutil.rmtree(document_dir, ignore_errors=True)
    return {"deleted": True}


@router.post("/source-documents/{source_document_id}/verify")
def verify_source_document(source_document_id: str, db: Session = Depends(get_db)):
    source = require_source_document(db, source_document_id)
    if source.doc_type == "rulebook":
        if not source.linked_document_id:
            raise HTTPException(status_code=409, detail="Rule book is not linked to a parsed document.")
        updated = (
            db.query(models.Rule)
            .filter(models.Rule.document_id == source.linked_document_id)
            .update({"review_status": "reviewed"}, synchronize_session=False)
        )
        source.status = "rules_verified"
        db.commit()
        return {"source_document_id": source.id, "rules_reviewed": updated}
    if source.doc_type == "template":
        updated = (
            db.query(models.TemplateField)
            .filter(models.TemplateField.source_document_id == source.id)
            .update({"review_status": "approved"}, synchronize_session=False)
        )
        source.status = "fields_verified"
        db.commit()
        return {"source_document_id": source.id, "fields_approved": updated}
    raise HTTPException(status_code=409, detail="Only rulebook and template sources can be verified here.")


@router.post("/templates/{document_id}/extract-fields", response_model=schemas.ExtractFieldsResponse)
def extract_template_fields(document_id: str, db: Session = Depends(get_db)):
    source = require_source_document(db, document_id)
    if source.doc_type != "template":
        raise HTTPException(status_code=409, detail="Template field extraction requires doc_type=template.")
    fields = build_template_fields(source, db)
    derived_prefix = f"{infer_template_doc(source.name).lower()}.derived.%"
    (
        db.query(models.TemplateField)
        .filter(
            models.TemplateField.source_document_id == source.id,
            models.TemplateField.field_key.like(derived_prefix),
            models.TemplateField.review_status.in_(["suggested", "needs_edit", "rejected"]),
        )
        .delete(synchronize_session=False)
    )
    created = 0
    for data in fields:
        existing = (
            db.query(models.TemplateField)
            .filter(
                models.TemplateField.collection_id == source.collection_id,
                models.TemplateField.field_key == data["field_key"],
            )
            .first()
        )
        if existing:
            for key in [
                "label",
                "anchor_text",
                "input_type",
                "section_ref",
                "extraction_hint",
                "source_document_id",
                "template_doc",
            ]:
                if key in data:
                    setattr(existing, key, data[key])
            if "required" in data:
                existing.required = bool(data["required"])
            continue
        db.add(models.TemplateField(id=f"tf-{uuid.uuid4().hex[:10]}", **data))
        created += 1
    source.status = "fields_extracted"
    db.commit()
    return schemas.ExtractFieldsResponse(document_id=source.id, fields_created=created)


@router.get("/template-fields", response_model=list[schemas.TemplateFieldRead])
def list_template_fields(
    collection_id: str | None = Query(None),
    template_doc: str | None = Query(None),
    review_status: str | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(models.TemplateField)
    if collection_id:
        query = query.filter(models.TemplateField.collection_id == collection_id)
    if template_doc:
        query = query.filter(models.TemplateField.template_doc == template_doc)
    if review_status:
        query = query.filter(models.TemplateField.review_status == review_status)
    return query.order_by(models.TemplateField.template_doc, models.TemplateField.field_key).all()


@router.put("/template-fields/{field_id}", response_model=schemas.TemplateFieldRead)
def update_template_field(field_id: str, payload: schemas.TemplateFieldUpdate, db: Session = Depends(get_db)):
    field = require_template_field(db, field_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(field, key, value)
    db.commit()
    db.refresh(field)
    return field


@router.delete("/template-fields/{field_id}")
def delete_template_field(field_id: str, db: Session = Depends(get_db)):
    field = require_template_field(db, field_id)
    db.delete(field)
    db.commit()
    return {"deleted": True}


@router.post("/mapping-runs", response_model=schemas.MappingRunRead)
def create_mapping_run(payload: schemas.MappingRunCreate, db: Session = Depends(get_db)):
    require_collection(db, payload.collection_id)
    config = get_runtime_config()
    run = models.MappingRun(
        id=f"mr-{uuid.uuid4().hex[:10]}",
        collection_id=payload.collection_id,
        status="running",
        llm_model=config.llm_model,
        artifact_json={},
    )
    db.add(run)
    db.commit()
    try:
        totals = suggest_field_rule_mappings(db, payload.collection_id)
        run.status = "completed"
        run.windows_total = totals["fields"]
        run.windows_completed = totals["fields"]
        run.failures = 0
        run.artifact_json = totals
        run.completed_at = datetime.now(timezone.utc)
    except Exception as exc:
        run.status = "failed"
        run.failures = 1
        run.error_message = str(exc)
    db.commit()
    db.refresh(run)
    return run


@router.get("/mapping-runs/{run_id}", response_model=schemas.MappingRunRead)
def get_mapping_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(models.MappingRun).filter(models.MappingRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Mapping run not found")
    return run


@router.get("/field-rule-mappings", response_model=list[schemas.FieldRuleMappingRead])
def list_field_rule_mappings(
    collection_id: str | None = Query(None),
    field_id: str | None = Query(None),
    review_status: str | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(models.FieldRuleMapping)
    if collection_id:
        query = query.filter(models.FieldRuleMapping.collection_id == collection_id)
    if field_id:
        query = query.filter(models.FieldRuleMapping.template_field_id == field_id)
    if review_status:
        query = query.filter(models.FieldRuleMapping.review_status == review_status)
    rows = query.order_by(models.FieldRuleMapping.confidence.desc()).all()
    return [mapping_read(db, row) for row in rows]


@router.put("/field-rule-mappings/{mapping_id}", response_model=schemas.FieldRuleMappingRead)
def update_field_rule_mapping(mapping_id: str, payload: schemas.FieldRuleMappingUpdate, db: Session = Depends(get_db)):
    mapping = require_field_rule_mapping(db, mapping_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(mapping, key, value)
    db.commit()
    db.refresh(mapping)
    return mapping_read(db, mapping)


@router.post("/tender-submissions", response_model=schemas.TenderSubmissionRead)
def create_tender_submission(payload: schemas.TenderSubmissionCreate, db: Session = Depends(get_db)):
    require_collection(db, payload.collection_id)
    submission = models.TenderSubmission(
        id=f"ts-{uuid.uuid4().hex[:10]}",
        status="created",
        **payload.model_dump(),
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission


@router.get("/tender-submissions", response_model=list[schemas.TenderSubmissionRead])
def list_tender_submissions(collection_id: str | None = Query(None), db: Session = Depends(get_db)):
    query = db.query(models.TenderSubmission)
    if collection_id:
        query = query.filter(models.TenderSubmission.collection_id == collection_id)
    return query.order_by(models.TenderSubmission.created_at.desc()).all()


@router.post("/tender-submissions/{submission_id}/extract-evidence", response_model=schemas.EvidenceExtractionResponse)
def extract_tender_evidence(submission_id: str, db: Session = Depends(get_db)):
    submission = require_tender_submission(db, submission_id)
    fields = (
        db.query(models.TemplateField)
        .filter(models.TemplateField.collection_id == submission.collection_id)
        .order_by(models.TemplateField.template_doc, models.TemplateField.field_key)
        .all()
    )
    created = 0
    db.query(models.TenderFieldEvidence).filter(models.TenderFieldEvidence.submission_id == submission.id).delete()
    for field in fields:
        value, raw_text, confidence, _found = extract_evidence_value(db, submission, field)
        db.add(
            models.TenderFieldEvidence(
                id=f"ev-{uuid.uuid4().hex[:10]}",
                submission_id=submission.id,
                template_field_id=field.id,
                value=value,
                raw_text=raw_text,
                source_document="; ".join(submission.source_document_ids),
                page_or_section=field.anchor_text[:120],
                confidence=confidence,
                review_status="suggested",
            )
        )
        created += 1
    submission.status = "evidence_extracted"
    db.commit()
    return schemas.EvidenceExtractionResponse(submission_id=submission.id, evidence_created=created)


@router.post("/tender-submissions/{submission_id}/run-checks", response_model=schemas.RunChecksResponse)
def run_submission_checks(submission_id: str, db: Session = Depends(get_db)):
    submission = require_tender_submission(db, submission_id)
    evidence_by_field = {
        evidence.template_field_id: evidence
        for evidence in db.query(models.TenderFieldEvidence).filter(models.TenderFieldEvidence.submission_id == submission.id)
    }
    mappings = (
        db.query(models.FieldRuleMapping)
        .filter(
            models.FieldRuleMapping.collection_id == submission.collection_id,
            models.FieldRuleMapping.review_status == "approved",
        )
        .all()
    )
    db.query(models.CheckResult).filter(models.CheckResult.submission_id == submission.id).delete()
    created = 0
    for mapping in mappings:
        field = db.query(models.TemplateField).filter(models.TemplateField.id == mapping.template_field_id).first()
        if not field:
            continue
        evidence = evidence_by_field.get(field.id)
        rule = db.query(models.Rule).filter(models.Rule.id == mapping.rule_id).first() if mapping.rule_id else None
        result, severity, reason = evaluate_result(field, mapping, evidence, rule)
        db.add(
            models.CheckResult(
                id=f"cr-{uuid.uuid4().hex[:10]}",
                submission_id=submission.id,
                template_field_id=field.id,
                mapping_id=mapping.id,
                result=result,
                severity=severity,
                reason=reason,
                rule_evidence=(rule.action if rule else mapping.rationale),
                tender_evidence=evidence.raw_text if evidence else "",
                review_status="draft",
            )
        )
        created += 1
    submission.status = "checked"
    db.commit()
    return schemas.RunChecksResponse(submission_id=submission.id, results_created=created)


@router.get("/tender-submissions/{submission_id}/results", response_model=list[schemas.CheckResultRead])
def list_check_results(submission_id: str, db: Session = Depends(get_db)):
    require_tender_submission(db, submission_id)
    return (
        db.query(models.CheckResult)
        .filter(models.CheckResult.submission_id == submission_id)
        .order_by(models.CheckResult.result, models.CheckResult.severity)
        .all()
    )


@router.delete("/tender-submissions/{submission_id}")
def delete_tender_submission(submission_id: str, db: Session = Depends(get_db)):
    submission = require_tender_submission(db, submission_id)
    db.delete(submission)
    db.commit()
    return {"deleted": True}


def mapping_read(db: Session, mapping: models.FieldRuleMapping) -> schemas.FieldRuleMappingRead:
    field = db.query(models.TemplateField).filter(models.TemplateField.id == mapping.template_field_id).first()
    rule = db.query(models.Rule).filter(models.Rule.id == mapping.rule_id).first() if mapping.rule_id else None
    return schemas.FieldRuleMappingRead(
        id=mapping.id,
        collection_id=mapping.collection_id,
        template_field_id=mapping.template_field_id,
        rule_id=mapping.rule_id,
        source_type=mapping.source_type,
        check_type=mapping.check_type,
        applicability_condition=mapping.applicability_condition,
        confidence=mapping.confidence,
        rationale=mapping.rationale,
        review_status=mapping.review_status,
        review_notes=mapping.review_notes,
        field_label=field.label if field else "",
        rule_subject=rule.subject if rule else None,
        created_at=mapping.created_at.isoformat() if mapping.created_at else None,
        updated_at=mapping.updated_at.isoformat() if mapping.updated_at else None,
    )


def require_collection(db: Session, collection_id: str) -> models.DocumentCollection:
    collection = db.query(models.DocumentCollection).filter(models.DocumentCollection.id == collection_id).first()
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    return collection


def require_source_document(db: Session, source_document_id: str) -> models.SourceDocument:
    source = db.query(models.SourceDocument).filter(models.SourceDocument.id == source_document_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source document not found")
    return source


def require_template_field(db: Session, field_id: str) -> models.TemplateField:
    field = db.query(models.TemplateField).filter(models.TemplateField.id == field_id).first()
    if not field:
        raise HTTPException(status_code=404, detail="Template field not found")
    return field


def require_field_rule_mapping(db: Session, mapping_id: str) -> models.FieldRuleMapping:
    mapping = db.query(models.FieldRuleMapping).filter(models.FieldRuleMapping.id == mapping_id).first()
    if not mapping:
        raise HTTPException(status_code=404, detail="Field rule mapping not found")
    return mapping


def require_tender_submission(db: Session, submission_id: str) -> models.TenderSubmission:
    submission = db.query(models.TenderSubmission).filter(models.TenderSubmission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Tender submission not found")
    return submission
