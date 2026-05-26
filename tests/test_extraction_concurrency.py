"""Verify extraction workers receive only primitives, not ORM objects."""
from backend.app.services.extraction import (
    chunked,
    classify_section_heuristic,
    coerce_confidence,
    normalize_rule,
    normalize_rule_type,
    normalize_review_status,
)
from unittest.mock import MagicMock


def test_chunked_splits_list_into_batches():
    items = list(range(10))
    batches = chunked(items, 3)
    assert batches == [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9]]
    assert len(batches) == 4


def test_normalize_rule_type_aliases():
    assert normalize_rule_type("procedural") == "procedure"
    assert normalize_rule_type("requirement") == "obligation"
    assert normalize_rule_type("required") == "obligation"
    assert normalize_rule_type("process") == "procedure"
    assert normalize_rule_type("obligation") == "obligation"
    assert normalize_rule_type("unknown_type") == "procedure"


def test_normalize_review_status_defaults_to_draft():
    assert normalize_review_status(None) == "draft"
    assert normalize_review_status("") == "draft"
    assert normalize_review_status("invalid") == "draft"
    assert normalize_review_status("reviewed") == "reviewed"
    assert normalize_review_status("rejected") == "rejected"


def test_coerce_confidence_clamps_to_0_1():
    assert coerce_confidence(0.5) == 0.5
    assert coerce_confidence(1.5) == 1.0
    assert coerce_confidence(-0.5) == 0.0
    assert coerce_confidence("invalid") == 0.5
    assert coerce_confidence(None) == 0.5


def test_classify_section_heuristic_returns_valid_classification():
    section = MagicMock()
    section.heading_path = ["Main"]
    section.content = "The Contractor shall submit the programme."
    classification, confidence = classify_section_heuristic(section)
    assert classification in {"background", "definition", "rule_candidate", "option_logic", "mixed", "table_only"}
    assert 0.0 <= confidence <= 1.0


def test_normalize_rule_works_with_dict_instead_of_section():
    """normalize_rule should accept a dict as section (for worker primitives)."""
    raw = {
        "source": {"evidence_text": "Test evidence"},
        "subject": "Test subject",
        "condition": None,
        "action": "Test action",
        "type": "obligation",
        "review_status": "draft",
        "confidence": 0.9,
    }
    section_dict = {
        "id": "section-1",
        "title": "Test Section",
        "content": "Test content",
        "heading_path": ["Main", "Test"],
    }
    normalized = normalize_rule(raw, document_id=1, section=section_dict)
    assert normalized["subject"] == "Test subject"
    assert normalized["document_id"] == 1
    assert normalized["section_id"] == "section-1"
    assert normalized["type"] == "obligation"
    assert normalized["confidence"] == 0.9