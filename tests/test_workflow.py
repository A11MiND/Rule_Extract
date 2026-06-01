from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models, schemas
from backend.app.database import Base
from backend.app.routers import workflow
from backend.app.services.llm import LLMClient


def _fake_complete_json(self: LLMClient, system_prompt: str, user_prompt: str) -> dict[str, Any]:
    """Stubbed LLM used by tests: returns deterministic JSON per call site."""
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
    assert any(field.field_key.startswith("cdp1.derived.") for field in fields)
    assert len(fields) > 7

    verified_template = workflow.verify_source_document(template_doc.id, db)
    assert verified_template["fields_approved"] == len(fields)

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
