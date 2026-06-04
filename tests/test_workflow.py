from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import main, models, schemas
from backend.app.database import Base
from backend.app.routers import workflow
from backend.app.services.audit import model_snapshot
from backend.app.services.llm import LLMClient


def _fake_complete_json(self: LLMClient, system_prompt: str, user_prompt: str) -> dict[str, Any]:
    """Stubbed LLM used by tests: returns deterministic JSON per call site."""
    if "reviewable tender-template fields" in system_prompt:
        return {
            "fields": [
                {
                    "field_key": "cdp1.main_option",
                    "label": "Selected main Option",
                    "part_ref": "A4.2 Option Selection",
                    "filled_by": "project_office",
                    "anchor_text": "clauses for main Option [insert selected main Option]",
                    "input_type": "enum",
                    "required": True,
                    "section_ref": "doc-101-section-1",
                    "extraction_hint": "Extract the selected main Option from CDP1.",
                    "confidence": 0.86,
                    "rationale": "The marker requests a selected main option.",
                },
                {
                    "field_key": "cdp1.site_information_refs",
                    "label": "Site Information document references",
                    "part_ref": "A4.2 Option Selection",
                    "filled_by": "project_office",
                    "anchor_text": "The Site Information is in the following documents: [insert reference].",
                    "input_type": "file_list",
                    "required": True,
                    "section_ref": "doc-101-section-1",
                    "extraction_hint": "Extract all Site Information document references.",
                    "confidence": 0.82,
                    "rationale": "The marker asks the project office to insert document references.",
                },
            ]
        }
    if "Pick the top 5 rules" in system_prompt or "top 5 rules" in system_prompt:
        return {
            "mappings": [
                {
                    "rule_id": "rule-main-option",
                    "confidence": 0.82,
                    "rationale": "Practice Note rule covers main Option selection, matching this CDP1 field.",
                }
            ]
        }
    if "extract a single value" in system_prompt.lower() or "extract the value" in system_prompt.lower():
        return {
            "value": "Main Option A",
            "raw_excerpt": "The conditions of contract are the clauses for main Option A.",
            "confidence": 0.78,
            "found": True,
        }
    return {
        "result": "needs_review",
        "severity": "medium",
        "reason": "Stubbed LLM check could not confirm against the rule.",
    }


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(LLMClient, "complete_json", _fake_complete_json)


@pytest.fixture()
def db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    seed_rulebook_document(session)
    try:
        yield session
    finally:
        session.close()


def test_template_mapping_vetting_flow_uses_only_approved_mappings(db: Session):
    collection = workflow.create_collection(
        schemas.CollectionCreate(name="NEC ECC HK Public Works POC", contract_family="ECC"),
        db,
    )
    template_doc = workflow.create_source_document(
        schemas.SourceDocumentCreate(
            collection_id=collection.id,
            doc_type="template",
            name="CDP1",
            linked_document_id=101,
        ),
        db,
    )

    extract_response = workflow.extract_template_fields(template_doc.id, db)
    assert extract_response.fields_created >= 1

    fields = workflow.list_template_fields(
        collection_id=collection.id,
        template_doc=None,
        review_status=None,
        db=db,
    )
    assert any(field.field_key == "cdp1.main_option" for field in fields)
    assert any(field.part_ref == "A4.2 Option Selection" for field in fields)
    assert all(field.review_status == "suggested" for field in fields)

    with pytest.raises(Exception):
        workflow.verify_source_document(template_doc.id, db)

    for field in fields:
        workflow.update_template_field(
            field.id,
            schemas.TemplateFieldUpdate(review_status="approved"),
            db,
        )
    verified_template = workflow.verify_source_document(template_doc.id, db)
    assert verified_template["fields_approved"] == len(fields)

    rule_source = workflow.create_source_document(
        schemas.SourceDocumentCreate(
            collection_id=collection.id,
            doc_type="rulebook",
            name="NEC ECC Practice Notes",
            linked_document_id=101,
        ),
        db,
    )
    workflow.verify_source_document(rule_source.id, db)

    mapping_run = workflow.create_mapping_run(schemas.MappingRunCreate(collection_id=collection.id), db)
    assert mapping_run.status == "completed"

    mappings = workflow.list_field_rule_mappings(
        collection_id=collection.id,
        field_id=None,
        review_status=None,
        db=db,
    )
    assert mappings
    first_mapping = mappings[0]
    assert first_mapping.review_status in {"suggested", "needs_edit"}

    approved_mapping = workflow.update_field_rule_mapping(
        first_mapping.id,
        schemas.FieldRuleMappingUpdate(review_status="approved"),
        db,
    )
    assert approved_mapping.review_status == "approved"

    tender_doc = workflow.create_source_document(
        schemas.SourceDocumentCreate(
            collection_id=collection.id,
            doc_type="tender_submission",
            name="Tender CDP1 response",
            linked_document_id=101,
        ),
        db,
    )
    submission = workflow.create_tender_submission(
        schemas.TenderSubmissionCreate(
            collection_id=collection.id,
            name="Submission 1",
            source_document_ids=[tender_doc.id],
        ),
        db,
    )

    evidence = workflow.extract_tender_evidence(submission.id, db)
    assert evidence.evidence_created == len(fields)

    checks = workflow.run_submission_checks(submission.id, db)
    assert checks.results_created == 1

    results = workflow.list_check_results(submission.id, db)
    assert len(results) == 1
    assert results[0].mapping_id == first_mapping.id
    assert results[0].result in {"needs_review", "fail", "not_applicable"}


def test_rulebook_verify_marks_extracted_rules_reviewed(db: Session):
    collection = workflow.create_collection(schemas.CollectionCreate(name="Rule Verify"), db)
    source_doc = workflow.create_source_document(
        schemas.SourceDocumentCreate(
            collection_id=collection.id,
            doc_type="rulebook",
            name="Practice Notes",
            linked_document_id=101,
        ),
        db,
    )

    response = workflow.verify_source_document(source_doc.id, db)
    rule = db.query(models.Rule).filter(models.Rule.id == "rule-main-option").first()

    assert response["rules_reviewed"] == 1
    assert rule.review_status == "reviewed"


def test_rulebook_verify_preserves_rejected_rules(db: Session):
    collection = workflow.create_collection(schemas.CollectionCreate(name="Rule Verify Rejects"), db)
    source_doc = workflow.create_source_document(
        schemas.SourceDocumentCreate(
            collection_id=collection.id,
            doc_type="rulebook",
            name="Practice Notes",
            linked_document_id=101,
        ),
        db,
    )
    rule = db.query(models.Rule).filter(models.Rule.id == "rule-main-option").first()
    rule.review_status = "rejected"
    db.commit()

    response = workflow.verify_source_document(source_doc.id, db)
    db.refresh(rule)

    assert response["rules_reviewed"] == 0
    assert rule.review_status == "rejected"


def test_document_markers_follow_source_document_role(db: Session):
    collection = workflow.create_collection(schemas.CollectionCreate(name="Marker Roles"), db)
    template_source = workflow.create_source_document(
        schemas.SourceDocumentCreate(
            collection_id=collection.id,
            doc_type="template",
            name="CDP1",
            linked_document_id=101,
        ),
        db,
    )

    template_markers = main.get_document_markers(101, "auto", db)
    assert any(marker.color == "blue" and "insert" in marker.text.lower() for marker in template_markers)

    workflow.delete_source_document(template_source.id, db)
    seed_rulebook_document(db)
    workflow.create_source_document(
        schemas.SourceDocumentCreate(
            collection_id=collection.id,
            doc_type="rulebook",
            name="Practice Notes",
            linked_document_id=101,
        ),
        db,
    )
    rule_markers = main.get_document_markers(101, "auto", db)
    assert all(marker.color == "yellow" for marker in rule_markers)


def test_delete_document_removes_history_and_linked_workflow_records(db: Session):
    collection = workflow.create_collection(schemas.CollectionCreate(name="Delete History"), db)
    source_doc = workflow.create_source_document(
        schemas.SourceDocumentCreate(
            collection_id=collection.id,
            doc_type="rulebook",
            name="Practice Notes",
            linked_document_id=101,
        ),
        db,
    )
    field = models.TemplateField(
        id="tf-delete-history",
        collection_id=collection.id,
        source_document_id=source_doc.id,
        template_doc="CDP1",
        field_key="cdp1.main_option",
        label="Selected main Option",
        anchor_text="main Option",
        input_type="enum",
        extraction_hint="Extract selected main Option.",
        review_status="approved",
    )
    db.add(field)
    db.add(
        models.FieldRuleMapping(
            id="frm-delete-history",
            collection_id=collection.id,
            template_field_id=field.id,
            rule_id="rule-main-option",
            source_type="rule",
            check_type="deterministic",
            confidence=0.9,
            rationale="test",
            review_status="suggested",
        )
    )
    db.commit()

    response = main.delete_document(101, db)

    assert response == {"deleted": True}
    assert db.query(models.Document).filter(models.Document.id == 101).count() == 0
    assert db.query(models.Section).filter(models.Section.document_id == 101).count() == 0
    assert db.query(models.Rule).filter(models.Rule.document_id == 101).count() == 0
    assert db.query(models.SourceDocument).filter(models.SourceDocument.linked_document_id == 101).count() == 0
    assert db.query(models.FieldRuleMapping).filter(models.FieldRuleMapping.id == "frm-delete-history").count() == 0


def test_delete_source_document_removes_linked_history_document(db: Session):
    collection = workflow.create_collection(schemas.CollectionCreate(name="Delete Source"), db)
    source_doc = workflow.create_source_document(
        schemas.SourceDocumentCreate(
            collection_id=collection.id,
            doc_type="rulebook",
            name="Practice Notes",
            linked_document_id=101,
        ),
        db,
    )
    field = models.TemplateField(
        id="tf-delete-source",
        collection_id=collection.id,
        source_document_id=None,
        template_doc="CDP1",
        field_key="cdp1.main_option",
        label="Selected main Option",
        anchor_text="main Option",
        input_type="enum",
        extraction_hint="Extract selected main Option.",
        review_status="approved",
    )
    db.add(field)
    db.add(
        models.FieldRuleMapping(
            id="frm-delete-source",
            collection_id=collection.id,
            template_field_id=field.id,
            rule_id="rule-main-option",
            source_type="rule",
            check_type="deterministic",
            confidence=0.9,
            rationale="test",
            review_status="suggested",
        )
    )
    db.commit()

    response = workflow.delete_source_document(source_doc.id, db)

    assert response == {"deleted": True}
    assert db.query(models.SourceDocument).filter(models.SourceDocument.id == source_doc.id).count() == 0
    assert db.query(models.Document).filter(models.Document.id == 101).count() == 0
    assert db.query(models.Rule).filter(models.Rule.document_id == 101).count() == 0
    assert db.query(models.FieldRuleMapping).filter(models.FieldRuleMapping.id == "frm-delete-source").count() == 0


def test_delete_source_document_removes_submission_reference_and_field_evidence(db: Session):
    collection = workflow.create_collection(schemas.CollectionCreate(name="Delete Source References"), db)
    source_doc = workflow.create_source_document(
        schemas.SourceDocumentCreate(collection_id=collection.id, doc_type="template", name="CDP1"),
        db,
    )
    field = models.TemplateField(
        id="tf-delete-evidence",
        collection_id=collection.id,
        source_document_id=source_doc.id,
        template_doc="CDP1",
        field_key="cdp1.delete",
        label="Delete me",
        anchor_text="delete",
        input_type="text",
        extraction_hint="delete",
    )
    submission = models.TenderSubmission(
        id="sub-delete-source",
        collection_id=collection.id,
        name="Submission",
        source_document_ids=[source_doc.id],
    )
    db.add_all([field, submission])
    db.flush()
    db.add(
        models.TenderFieldEvidence(
            id="ev-delete-source",
            submission_id=submission.id,
            template_field_id=field.id,
            source_document=source_doc.id,
        )
    )
    db.commit()

    workflow.delete_source_document(source_doc.id, db)
    db.refresh(submission)

    assert submission.source_document_ids == []
    assert db.query(models.TenderFieldEvidence).filter(models.TenderFieldEvidence.id == "ev-delete-source").count() == 0


def test_collection_delete_cascades_workflow_records(db: Session):
    collection = workflow.create_collection(schemas.CollectionCreate(name="Delete Me"), db)
    source_doc = workflow.create_source_document(
        schemas.SourceDocumentCreate(collection_id=collection.id, doc_type="template", name="FOT"),
        db,
    )
    workflow.extract_template_fields(source_doc.id, db)
    workflow.create_mapping_run(schemas.MappingRunCreate(collection_id=collection.id), db)
    submission = workflow.create_tender_submission(
        schemas.TenderSubmissionCreate(collection_id=collection.id, name="Submission", source_document_ids=[]),
        db,
    )
    workflow.extract_tender_evidence(submission.id, db)

    response = workflow.delete_collection(collection.id, db)
    assert response == {"deleted": True}

    assert workflow.list_source_documents(collection_id=collection.id, doc_type=None, db=db) == []
    assert workflow.list_template_fields(
        collection_id=collection.id,
        template_doc=None,
        review_status=None,
        db=db,
    ) == []
    assert workflow.list_field_rule_mappings(
        collection_id=collection.id,
        field_id=None,
        review_status=None,
        db=db,
    ) == []
    assert workflow.list_tender_submissions(collection_id=collection.id, db=db) == []
    assert db.query(models.MappingRun).filter(models.MappingRun.collection_id == collection.id).count() == 0


def seed_rulebook_document(db: Session) -> None:
    doc = models.Document(
        id=101,
        name="Practice Notes",
        pdf_url="https://example.test/practice-notes.pdf",
        status="rules_extracted",
    )
    db.add(doc)
    db.add(
        models.Section(
            id="doc-101-section-1",
            document_id=101,
            position=1,
            level=2,
            title="A4.2 Option Selection",
            heading_path=["A4", "A4.2"],
            content=(
                "The conditions of contract are the clauses for main Option [insert selected main Option]. "
                "The works are [insert brief description of the works]. "
                "The Site Information is in the following documents: [insert reference]. "
                "The tender closing date is [insert date]."
            ),
        )
    )
    db.add(
        models.Rule(
            id="rule-main-option",
            document_id=101,
            section_id="doc-101-section-1",
            source={"heading_path": ["A4", "A4.2"], "evidence_text": "Select a main Option."},
            subject="Main Option selection",
            condition="When preparing CDP1",
            action="Project Offices should select and state the applicable main Option.",
            type="obligation",
            confidence=0.9,
        )
    )
    db.commit()


def test_professionalization_workflow_is_document_scoped_and_audited(db: Session):
    collection = workflow.create_collection(schemas.CollectionCreate(name="Professional Workspace"), db)
    slots = workflow.list_library_slots(collection_id=collection.id, db=db)
    assert len(slots) == 9
    assert any(slot.required and slot.doc_type == "template" for slot in slots)

    source = workflow.create_source_document(
        schemas.SourceDocumentCreate(
            collection_id=collection.id,
            doc_type="rulebook",
            name="Selected Rule Book",
            linked_document_id=101,
        ),
        db,
    )
    confirmed = workflow.confirm_source_text(source.id, db)
    assert confirmed.text_review_status == "verified"
    assert len(confirmed.content_fingerprint) == 64

    rule = db.query(models.Rule).filter(models.Rule.id == "rule-main-option").one()
    rule.review_status = "rejected"
    db.commit()
    workflow.bulk_review_rules(source.id, schemas.RuleBulkReview(review_status="reviewed"), db)
    db.refresh(rule)
    assert rule.review_status == "rejected"

    summary = workflow.get_dashboard_summary(collection_id=collection.id, db=db)
    assert summary.total_documents == 1
    assert summary.awaiting_text_review == 0
    assert summary.recent_activity


def test_approved_procedure_sets_are_immutable_and_cloneable(db: Session):
    collection = workflow.create_collection(schemas.CollectionCreate(name="Procedure Workspace"), db)
    draft = workflow.create_procedure_set(
        schemas.ProcedureSetCreate(collection_id=collection.id, name="Tender Vetting Procedure"),
        db,
    )
    approved = workflow.approve_procedure_set(draft.id, db)
    assert approved.status == "approved"

    with pytest.raises(Exception):
        workflow.update_procedure_set(
            approved.id,
            schemas.ProcedureSetUpdate(name="Changed approved procedure"),
            db,
        )

    clone = workflow.clone_procedure_set(approved.id, db)
    assert clone.status == "draft"
    assert clone.version == approved.version + 1
    assert clone.parent_id == approved.id


def test_audit_redaction_and_openapi_document_new_workflows():
    snapshot = model_snapshot(
        {
            "llm_api_key": "secret",
            "mineru_api_token": "secret",
            "content": "large document body",
            "name": "Visible",
        }
    )
    assert snapshot["llm_api_key"] == "[redacted]"
    assert snapshot["mineru_api_token"] == "[redacted]"
    assert snapshot["content"] == "[redacted]"
    assert snapshot["name"] == "Visible"

    schema = main.app.openapi()
    assert schema["info"]["title"] == "Tender Vetting API"
    for path in [
        "/api/library-slots",
        "/api/source-documents/import-url",
        "/api/source-documents/{source_document_id}/confirm-text",
        "/api/mapping-runs",
        "/api/procedure-sets/{procedure_id}/approve",
        "/api/audit-events",
        "/api/dashboard-summary",
    ]:
        assert path in schema["paths"]
