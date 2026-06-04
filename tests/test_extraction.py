import json
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models
from backend.app.config import settings
from backend.app.database import Base
from backend.app.schemas import RuleBase
from backend.app.services.extraction import (
    append_llm_window_log,
    llm_windows_path,
    normalize_rule,
    save_rule_if_new_batch,
    section_snapshot,
)


def test_append_llm_window_log_writes_jsonl_with_path_storage(tmp_path):
    previous_storage_root = settings.storage_root
    object.__setattr__(settings, "storage_root", tmp_path)
    try:
        append_llm_window_log(42, {"kind": "extraction", "status": "failed", "error": "rate limit"})

        path = llm_windows_path(42)
        payload = json.loads(path.read_text(encoding="utf-8").strip())
    finally:
        object.__setattr__(settings, "storage_root", previous_storage_root)

    assert path.name == "llm_windows.jsonl"
    assert payload["kind"] == "extraction"
    assert payload["status"] == "failed"
    assert payload["error"] == "rate limit"
    assert "timestamp" in payload


def test_normalize_rule_accepts_list_action_from_llm():
    section = SimpleNamespace(
        id="section-1",
        title="B4.2.4.22 Currency rule",
        content="Contract Data Part one should stipulate Hong Kong Dollar.",
        heading_path=["B4", "B4.2.4.22"],
    )

    normalized = normalize_rule(
        {
            "source": {"evidence_text": "Currency must be HKD.", "coordinates": None},
            "subject": "Contract currency",
            "condition": None,
            "action": ["Stipulate Hong Kong Dollar", "Do not include irrelevant secondary option"],
            "type": "obligation",
            "review_status": "draft",
            "confidence": 1,
        },
        document_id=3,
        section=section,
    )
    validated = RuleBase.model_validate(normalized)

    assert validated.action == "Stipulate Hong Kong Dollar; Do not include irrelevant secondary option"
    assert validated.condition == ""
    assert validated.source.coordinates == []


def test_save_rule_batch_preserves_human_reviewed_rule():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    document = models.Document(id=1, name="Rules", pdf_url="https://example.test/rules.pdf")
    existing = models.Rule(
        id="rule-1-fixed",
        document_id=1,
        subject="Human reviewed subject",
        action="Human reviewed action",
        review_status="reviewed",
    )
    db.add_all([document, existing])
    db.commit()

    created = save_rule_if_new_batch(
        db,
        document,
        {
            "source": {},
            "document_id": 1,
            "section_id": None,
            "subject": "LLM replacement",
            "condition": "",
            "action": "LLM replacement",
            "type": "obligation",
            "review_status": "draft",
            "confidence": 0.8,
            "notes": "",
            "options": [],
            "dependencies": [],
            "next_rule_ids": [],
        },
        rule_id="rule-1-fixed",
    )
    db.commit()
    db.refresh(existing)

    assert created == 0
    assert existing.subject == "Human reviewed subject"
    assert existing.review_status == "reviewed"


def test_section_snapshot_contains_only_plain_values():
    section = SimpleNamespace(
        id="section-1",
        title="Title",
        content="Content",
        heading_path=["Part", "Title"],
    )

    assert section_snapshot(section) == {
        "id": "section-1",
        "title": "Title",
        "content": "Content",
        "heading_path": ["Part", "Title"],
    }
