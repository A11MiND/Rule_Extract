from backend.app.main import scoped_section_id


def test_scoped_section_id_prevents_cross_document_collisions():
    assert scoped_section_id(4, "section-001-main") == "doc-4-section-001-main"
    assert scoped_section_id(4, "doc-4-section-001-main") == "doc-4-section-001-main"
