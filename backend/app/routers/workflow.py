from __future__ import annotations

import uuid
import shutil
import hashlib
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
from ..services.audit import model_snapshot, record_audit
from ..services.template_parser import (
    build_template_fields,
    infer_template_doc,
)

router = APIRouter(prefix="/api", tags=["workflow"])


DEFAULT_LIBRARY_SLOTS = [
    ("NEC ECC Practice Notes", "NEC ECC PN", "rulebook", True, 2, "Primary NEC ECC guidance and rule source."),
    ("GCT", "GCT", "rulebook", False, 2, "General Conditions of Tender reference source."),
    ("SCT", "SCT", "rulebook", False, 2, "Special Conditions of Tender reference source."),
    ("NTT", "NTT", "rulebook", False, 2, "Notes to Tenderers reference source."),
    ("ACC", "ACC", "reference_clause", False, 2, "Additional Conditions of Contract reference source."),
    ("CDP1 Tender Template", "CDP1", "template", True, 3, "Contract Data Part One template."),
    ("CDP2 Tender Template", "CDP2", "template", False, 3, "Contract Data Part Two template."),
    ("Form of Tender", "FOT", "template", False, 3, "Form of Tender template."),
    ("Articles of Agreement", "AOA", "template", False, 3, "Articles of Agreement template."),
]


@router.post("/collections", response_model=schemas.CollectionRead)
def create_collection(payload: schemas.CollectionCreate, db: Session = Depends(get_db)):
    collection = models.DocumentCollection(id=f"col-{uuid.uuid4().hex[:10]}", **payload.model_dump())
    db.add(collection)
    db.flush()
    seed_library_slots(db, collection.id)
    record_audit(
        db,
        action="create",
        entity_type="collection",
        entity_id=collection.id,
        summary=f"Created workspace {collection.name}",
        after=collection,
    )
    db.commit()
    db.refresh(collection)
    return collection


@router.get("/collections", response_model=list[schemas.CollectionRead])
def list_collections(db: Session = Depends(get_db)):
    return db.query(models.DocumentCollection).order_by(models.DocumentCollection.created_at.desc()).all()


@router.delete("/collections/{collection_id}")
def delete_collection(collection_id: str, db: Session = Depends(get_db)):
    collection = require_collection(db, collection_id)
    before = model_snapshot(collection)
    db.delete(collection)
    record_audit(
        db,
        action="delete",
        entity_type="collection",
        entity_id=collection_id,
        summary=f"Deleted workspace {collection.name}",
        before=before,
    )
    db.commit()
    return {"deleted": True}


@router.get("/library-slots", response_model=list[schemas.LibrarySlotRead])
def list_library_slots(collection_id: str | None = Query(None), db: Session = Depends(get_db)):
    query = db.query(models.LibrarySlot)
    if collection_id:
        query = query.filter(models.LibrarySlot.collection_id == collection_id)
    return query.order_by(models.LibrarySlot.sort_order, models.LibrarySlot.created_at).all()


@router.post("/library-slots", response_model=schemas.LibrarySlotRead)
def create_library_slot(payload: schemas.LibrarySlotCreate, db: Session = Depends(get_db)):
    require_collection(db, payload.collection_id)
    slot = models.LibrarySlot(id=f"slot-{uuid.uuid4().hex[:10]}", **payload.model_dump())
    db.add(slot)
    record_audit(
        db,
        action="create",
        entity_type="library_slot",
        entity_id=slot.id,
        summary=f"Added library placeholder {slot.name}",
        after=slot,
    )
    db.commit()
    db.refresh(slot)
    return slot


@router.patch("/library-slots/{slot_id}", response_model=schemas.LibrarySlotRead)
def update_library_slot(slot_id: str, payload: schemas.LibrarySlotUpdate, db: Session = Depends(get_db)):
    slot = require_library_slot(db, slot_id)
    before = model_snapshot(slot)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(slot, key, value)
    record_audit(
        db,
        action="update",
        entity_type="library_slot",
        entity_id=slot.id,
        summary=f"Updated library placeholder {slot.name}",
        before=before,
        after=slot,
    )
    db.commit()
    db.refresh(slot)
    return slot


@router.delete("/library-slots/{slot_id}")
def delete_library_slot(slot_id: str, db: Session = Depends(get_db)):
    slot = require_library_slot(db, slot_id)
    before = model_snapshot(slot)
    db.delete(slot)
    record_audit(
        db,
        action="delete",
        entity_type="library_slot",
        entity_id=slot.id,
        summary=f"Deleted library placeholder {slot.name}",
        before=before,
    )
    db.commit()
    return {"deleted": True}


@router.post("/source-documents", response_model=schemas.SourceDocumentRead)
def create_source_document(payload: schemas.SourceDocumentCreate, db: Session = Depends(get_db)):
    require_collection(db, payload.collection_id)
    if payload.slot_id:
        require_library_slot(db, payload.slot_id)
    source = models.SourceDocument(
        id=f"src-{uuid.uuid4().hex[:10]}",
        status="created",
        mineru_artifacts={},
        **payload.model_dump(),
    )
    db.add(source)
    record_audit(
        db,
        action="create",
        entity_type="source_document",
        entity_id=source.id,
        summary=f"Added source document {source.name}",
        after=source,
    )
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


@router.get("/source-documents/{source_document_id}", response_model=schemas.SourceDocumentRead)
def get_source_document(source_document_id: str, db: Session = Depends(get_db)):
    return require_source_document(db, source_document_id)


@router.patch("/source-documents/{source_document_id}", response_model=schemas.SourceDocumentRead)
def update_source_document(
    source_document_id: str,
    payload: schemas.SourceDocumentUpdate,
    db: Session = Depends(get_db),
):
    source = require_source_document(db, source_document_id)
    before = model_snapshot(source)
    data = payload.model_dump(exclude_unset=True)
    if data.get("slot_id"):
        require_library_slot(db, data["slot_id"])
    for key, value in data.items():
        setattr(source, key, value)
    record_audit(
        db,
        action="update",
        entity_type="source_document",
        entity_id=source.id,
        summary=f"Updated source document {source.name}",
        before=before,
        after=source,
    )
    db.commit()
    db.refresh(source)
    return source


@router.delete("/source-documents/{source_document_id}")
def delete_source_document(source_document_id: str, db: Session = Depends(get_db)):
    source = require_source_document(db, source_document_id)
    before = model_snapshot(source)
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
    record_audit(
        db,
        action="delete",
        entity_type="source_document",
        entity_id=source.id,
        summary=f"Deleted source document {source.name}",
        before=before,
    )
    db.commit()
    if document_dir and document_dir.exists():
        shutil.rmtree(document_dir, ignore_errors=True)
    return {"deleted": True}


@router.post("/source-documents/{source_document_id}/verify")
def verify_source_document(source_document_id: str, db: Session = Depends(get_db)):
    source = require_source_document(db, source_document_id)
    before = model_snapshot(source)
    if source.doc_type in {"rulebook", "reference_clause"}:
        if not source.linked_document_id:
            raise HTTPException(status_code=409, detail="Rule book is not linked to a parsed document.")
        updated = (
            db.query(models.Rule)
            .filter(models.Rule.document_id == source.linked_document_id)
            .update({"review_status": "reviewed"}, synchronize_session=False)
        )
        source.status = "rules_verified"
        record_audit(
            db,
            action="approve_all",
            entity_type="source_document",
            entity_id=source.id,
            summary=f"Approved all outstanding rules for {source.name}",
            before=before,
            after=source,
        )
        db.commit()
        return {"source_document_id": source.id, "rules_reviewed": updated}
    if source.doc_type == "template":
        fields = (
            db.query(models.TemplateField)
            .filter(models.TemplateField.source_document_id == source.id)
            .all()
        )
        if not fields:
            raise HTTPException(status_code=409, detail="Extract template fields before confirming this source.")
        open_count = sum(1 for field in fields if field.review_status in {"suggested", "needs_edit"})
        if open_count:
            raise HTTPException(status_code=409, detail="Review every suggested template field before confirming this source.")
        approved = sum(1 for field in fields if field.review_status == "approved")
        rejected = sum(1 for field in fields if field.review_status == "rejected")
        source.status = "fields_verified"
        record_audit(
            db,
            action="confirm",
            entity_type="source_document",
            entity_id=source.id,
            summary=f"Confirmed template fields for {source.name}",
            before=before,
            after=source,
        )
        db.commit()
        return {"source_document_id": source.id, "fields_approved": approved, "fields_rejected": rejected}
    raise HTTPException(status_code=409, detail="Only rulebook, reference, and template sources can be verified here.")


@router.post("/source-documents/{source_document_id}/confirm-text", response_model=schemas.SourceDocumentRead)
def confirm_source_text(source_document_id: str, db: Session = Depends(get_db)):
    source = require_source_document(db, source_document_id)
    if not source.linked_document_id:
        raise HTTPException(status_code=409, detail="Source is not linked to a converted document.")
    sections = (
        db.query(models.Section)
        .filter(models.Section.document_id == source.linked_document_id)
        .order_by(models.Section.position)
        .all()
    )
    if not sections:
        raise HTTPException(status_code=409, detail="Converted document text is not ready.")
    before = model_snapshot(source)
    fingerprint_text = "\n".join(f"{section.title}\n{section.content}" for section in sections)
    source.content_fingerprint = hashlib.sha256(fingerprint_text.encode("utf-8")).hexdigest()
    source.text_review_status = "verified"
    source.text_verified_at = datetime.now(timezone.utc)
    record_audit(
        db,
        action="confirm_text",
        entity_type="source_document",
        entity_id=source.id,
        summary=f"Confirmed converted text for {source.name}",
        before=before,
        after=source,
    )
    db.commit()
    db.refresh(source)
    return source


@router.post("/source-documents/{source_document_id}/rules/bulk-review")
def bulk_review_rules(
    source_document_id: str,
    payload: schemas.RuleBulkReview,
    db: Session = Depends(get_db),
):
    source = require_source_document(db, source_document_id)
    if not source.linked_document_id:
        raise HTTPException(status_code=409, detail="Source is not linked to extracted rules.")
    query = db.query(models.Rule).filter(models.Rule.document_id == source.linked_document_id)
    if payload.review_status == "reviewed":
        query = query.filter(models.Rule.review_status != "rejected")
    updated = query.update({"review_status": payload.review_status}, synchronize_session=False)
    record_audit(
        db,
        action="bulk_review",
        entity_type="rule",
        entity_id=source.id,
        summary=f"Set {updated} rules to {payload.review_status} for {source.name}",
        after={"review_status": payload.review_status, "updated": updated},
    )
    db.commit()
    return {"updated": updated, "review_status": payload.review_status}


@router.post("/source-documents/{source_document_id}/fields/bulk-review")
def bulk_review_source_fields(
    source_document_id: str,
    payload: schemas.TemplateFieldBulkReview,
    db: Session = Depends(get_db),
):
    source = require_source_document(db, source_document_id)
    query = db.query(models.TemplateField).filter(models.TemplateField.source_document_id == source.id)
    if payload.review_status == "approved":
        query = query.filter(models.TemplateField.review_status != "rejected")
    updated = query.update({"review_status": payload.review_status}, synchronize_session=False)
    record_audit(
        db,
        action="bulk_review",
        entity_type="template_field",
        entity_id=source.id,
        summary=f"Set {updated} fields to {payload.review_status} for {source.name}",
        after={"review_status": payload.review_status, "updated": updated},
    )
    db.commit()
    return {"updated": updated, "review_status": payload.review_status}


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
            models.TemplateField.review_status.in_(["suggested", "needs_edit"]),
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
            if existing.review_status in {"approved", "rejected"}:
                continue
            for key in [
                "label",
                "anchor_text",
                "input_type",
                "section_ref",
                "extraction_hint",
                "source_document_id",
                "template_doc",
                "part_ref",
                "filled_by",
                "confidence",
                "rationale",
                "source_window",
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


@router.post("/template-fields", response_model=schemas.TemplateFieldRead)
def create_template_field(payload: schemas.TemplateFieldCreate, db: Session = Depends(get_db)):
    require_collection(db, payload.collection_id)
    if payload.source_document_id:
        require_source_document(db, payload.source_document_id)
    field = models.TemplateField(id=f"tf-{uuid.uuid4().hex[:10]}", **payload.model_dump())
    db.add(field)
    record_audit(
        db,
        action="create",
        entity_type="template_field",
        entity_id=field.id,
        summary=f"Added template field {field.label}",
        after=field,
    )
    db.commit()
    db.refresh(field)
    return field


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
    return query.order_by(
        models.TemplateField.template_doc,
        models.TemplateField.source_document_id,
        models.TemplateField.section_ref,
        models.TemplateField.created_at,
        models.TemplateField.field_key,
    ).all()


@router.put("/template-fields/{field_id}", response_model=schemas.TemplateFieldRead)
def update_template_field(field_id: str, payload: schemas.TemplateFieldUpdate, db: Session = Depends(get_db)):
    field = require_template_field(db, field_id)
    before = model_snapshot(field)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(field, key, value)
    record_audit(
        db,
        action="update",
        entity_type="template_field",
        entity_id=field.id,
        summary=f"Updated template field {field.label}",
        before=before,
        after=field,
    )
    db.commit()
    db.refresh(field)
    return field


@router.post("/template-fields/bulk-review")
def bulk_review_template_fields(payload: schemas.TemplateFieldBulkReview, db: Session = Depends(get_db)):
    query = db.query(models.TemplateField)
    if payload.field_ids:
        query = query.filter(models.TemplateField.id.in_(payload.field_ids))
    updated = query.update({"review_status": payload.review_status}, synchronize_session=False)
    record_audit(
        db,
        action="bulk_review",
        entity_type="template_field",
        entity_id=",".join(payload.field_ids[:5]) or "all",
        summary=f"Set {updated} template fields to {payload.review_status}",
        after={"review_status": payload.review_status, "updated": updated},
    )
    db.commit()
    return {"updated": updated, "review_status": payload.review_status}


@router.delete("/template-fields/{field_id}")
def delete_template_field(field_id: str, db: Session = Depends(get_db)):
    field = require_template_field(db, field_id)
    before = model_snapshot(field)
    db.delete(field)
    record_audit(
        db,
        action="delete",
        entity_type="template_field",
        entity_id=field.id,
        summary=f"Deleted template field {field.label}",
        before=before,
    )
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
        totals = suggest_field_rule_mappings(
            db,
            payload.collection_id,
            template_source_ids=payload.template_source_ids,
            rule_source_ids=payload.rule_source_ids,
        )
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
    record_audit(
        db,
        action="run_mapping",
        entity_type="mapping_run",
        entity_id=run.id,
        summary=f"Generated mapping suggestions for {run.windows_total} fields",
        after=run,
        actor="System",
    )
    db.commit()
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
    before = model_snapshot(mapping)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(mapping, key, value)
    record_audit(
        db,
        action="update",
        entity_type="field_rule_mapping",
        entity_id=mapping.id,
        summary=f"Updated mapping {mapping.id}",
        before=before,
        after=mapping,
    )
    db.commit()
    db.refresh(mapping)
    return mapping_read(db, mapping)


@router.post("/field-rule-mappings", response_model=schemas.FieldRuleMappingRead)
def create_field_rule_mapping(
    payload: schemas.FieldRuleMappingCreateRequest,
    db: Session = Depends(get_db),
):
    require_collection(db, payload.collection_id)
    require_template_field(db, payload.template_field_id)
    mapping = models.FieldRuleMapping(id=f"frm-{uuid.uuid4().hex[:10]}", **payload.model_dump())
    db.add(mapping)
    record_audit(
        db,
        action="create",
        entity_type="field_rule_mapping",
        entity_id=mapping.id,
        summary=f"Added mapping for field {mapping.template_field_id}",
        after=mapping,
    )
    db.commit()
    db.refresh(mapping)
    return mapping_read(db, mapping)


@router.delete("/field-rule-mappings/{mapping_id}")
def delete_field_rule_mapping(mapping_id: str, db: Session = Depends(get_db)):
    mapping = require_field_rule_mapping(db, mapping_id)
    before = model_snapshot(mapping)
    db.delete(mapping)
    record_audit(
        db,
        action="delete",
        entity_type="field_rule_mapping",
        entity_id=mapping.id,
        summary=f"Deleted mapping {mapping.id}",
        before=before,
    )
    db.commit()
    return {"deleted": True}


@router.get("/procedure-sets", response_model=list[schemas.ProcedureSetRead])
def list_procedure_sets(collection_id: str | None = Query(None), db: Session = Depends(get_db)):
    query = db.query(models.VettingProcedureSet)
    if collection_id:
        query = query.filter(models.VettingProcedureSet.collection_id == collection_id)
    return query.order_by(models.VettingProcedureSet.updated_at.desc()).all()


@router.post("/procedure-sets", response_model=schemas.ProcedureSetRead)
def create_procedure_set(payload: schemas.ProcedureSetCreate, db: Session = Depends(get_db)):
    require_collection(db, payload.collection_id)
    procedure = models.VettingProcedureSet(
        id=f"proc-{uuid.uuid4().hex[:10]}",
        version=1,
        status="draft",
        **payload.model_dump(),
    )
    db.add(procedure)
    record_audit(
        db,
        action="create",
        entity_type="procedure_set",
        entity_id=procedure.id,
        summary=f"Created draft procedure set {procedure.name}",
        after=procedure,
    )
    db.commit()
    db.refresh(procedure)
    return procedure


@router.patch("/procedure-sets/{procedure_id}", response_model=schemas.ProcedureSetRead)
def update_procedure_set(
    procedure_id: str,
    payload: schemas.ProcedureSetUpdate,
    db: Session = Depends(get_db),
):
    procedure = require_procedure_set(db, procedure_id)
    if procedure.status == "approved":
        raise HTTPException(status_code=409, detail="Approved procedure sets are immutable. Clone it to create a new draft.")
    before = model_snapshot(procedure)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(procedure, key, value)
    record_audit(
        db,
        action="update",
        entity_type="procedure_set",
        entity_id=procedure.id,
        summary=f"Updated draft procedure set {procedure.name}",
        before=before,
        after=procedure,
    )
    db.commit()
    db.refresh(procedure)
    return procedure


@router.post("/procedure-sets/{procedure_id}/approve", response_model=schemas.ProcedureSetRead)
def approve_procedure_set(procedure_id: str, db: Session = Depends(get_db)):
    procedure = require_procedure_set(db, procedure_id)
    if procedure.status == "approved":
        return procedure
    before = model_snapshot(procedure)
    invalid_mappings = (
        db.query(models.FieldRuleMapping)
        .filter(
            models.FieldRuleMapping.id.in_(procedure.mapping_ids or [""]),
            models.FieldRuleMapping.review_status != "approved",
        )
        .count()
    )
    if invalid_mappings:
        raise HTTPException(status_code=409, detail="Approve every mapping included in the procedure set first.")
    procedure.status = "approved"
    procedure.approved_at = datetime.now(timezone.utc)
    record_audit(
        db,
        action="approve",
        entity_type="procedure_set",
        entity_id=procedure.id,
        summary=f"Approved procedure set {procedure.name} v{procedure.version}",
        before=before,
        after=procedure,
    )
    db.commit()
    db.refresh(procedure)
    return procedure


@router.post("/procedure-sets/{procedure_id}/clone", response_model=schemas.ProcedureSetRead)
def clone_procedure_set(procedure_id: str, db: Session = Depends(get_db)):
    source = require_procedure_set(db, procedure_id)
    clone = models.VettingProcedureSet(
        id=f"proc-{uuid.uuid4().hex[:10]}",
        collection_id=source.collection_id,
        name=source.name,
        version=source.version + 1,
        status="draft",
        template_source_ids=list(source.template_source_ids or []),
        rule_source_ids=list(source.rule_source_ids or []),
        mapping_ids=list(source.mapping_ids or []),
        parent_id=source.id,
    )
    db.add(clone)
    record_audit(
        db,
        action="clone",
        entity_type="procedure_set",
        entity_id=clone.id,
        summary=f"Created draft {clone.name} v{clone.version} from v{source.version}",
        after=clone,
    )
    db.commit()
    db.refresh(clone)
    return clone


@router.get("/audit-events", response_model=list[schemas.AuditEventRead])
def list_audit_events(
    entity_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(models.AuditEvent)
    if entity_type:
        query = query.filter(models.AuditEvent.entity_type == entity_type)
    return query.order_by(models.AuditEvent.created_at.desc()).limit(limit).all()


@router.get("/dashboard-summary", response_model=schemas.DashboardSummary)
def get_dashboard_summary(collection_id: str | None = Query(None), db: Session = Depends(get_db)):
    source_query = db.query(models.SourceDocument)
    if collection_id:
        source_query = source_query.filter(models.SourceDocument.collection_id == collection_id)
    sources = source_query.all()
    source_ids = [source.id for source in sources]
    linked_ids = [source.linked_document_id for source in sources if source.linked_document_id]
    awaiting_records = 0
    if source_ids:
        awaiting_records += (
            db.query(models.TemplateField)
            .filter(
                models.TemplateField.source_document_id.in_(source_ids),
                models.TemplateField.review_status.in_(["suggested", "needs_edit"]),
            )
            .count()
        )
    if linked_ids:
        awaiting_records += (
            db.query(models.Rule)
            .filter(
                models.Rule.document_id.in_(linked_ids),
                models.Rule.review_status == "draft",
            )
            .count()
        )
    procedure_query = db.query(models.VettingProcedureSet).filter(models.VettingProcedureSet.status == "approved")
    if collection_id:
        procedure_query = procedure_query.filter(models.VettingProcedureSet.collection_id == collection_id)
    running = {"created", "mineru_queued", "mineru_processing", "rule_extraction_queued", "extracting_rules"}
    failed = {"mineru_failed", "rule_extraction_failed"}
    return schemas.DashboardSummary(
        total_documents=len(sources),
        awaiting_text_review=sum(1 for source in sources if source.text_review_status != "verified"),
        awaiting_record_review=awaiting_records,
        processing=sum(1 for source in sources if source.status in running),
        failed=sum(1 for source in sources if source.status in failed),
        approved_procedure_sets=procedure_query.count(),
        recent_activity=db.query(models.AuditEvent).order_by(models.AuditEvent.created_at.desc()).limit(8).all(),
    )


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


def require_library_slot(db: Session, slot_id: str) -> models.LibrarySlot:
    slot = db.query(models.LibrarySlot).filter(models.LibrarySlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Library slot not found")
    return slot


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


def require_procedure_set(db: Session, procedure_id: str) -> models.VettingProcedureSet:
    procedure = (
        db.query(models.VettingProcedureSet)
        .filter(models.VettingProcedureSet.id == procedure_id)
        .first()
    )
    if not procedure:
        raise HTTPException(status_code=404, detail="Procedure set not found")
    return procedure


def require_tender_submission(db: Session, submission_id: str) -> models.TenderSubmission:
    submission = db.query(models.TenderSubmission).filter(models.TenderSubmission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Tender submission not found")
    return submission


def seed_library_slots(db: Session, collection_id: str) -> None:
    if db.query(models.LibrarySlot).filter(models.LibrarySlot.collection_id == collection_id).count():
        return
    for index, (name, short_name, doc_type, required, grouping_level, description) in enumerate(
        DEFAULT_LIBRARY_SLOTS
    ):
        db.add(
            models.LibrarySlot(
                id=f"slot-{uuid.uuid4().hex[:10]}",
                collection_id=collection_id,
                name=name,
                short_name=short_name,
                description=description,
                doc_type=doc_type,
                required=required,
                grouping_level=grouping_level,
                sort_order=index,
            )
        )
