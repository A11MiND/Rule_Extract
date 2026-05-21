import json

from backend.app.services.markdown import (
    build_section_tree,
    parse_markdown_sections,
    parse_mineru_content_sections,
)


def test_parse_markdown_sections_preserves_heading_paths():
    markdown = """# Main
Intro text.

## Clause 1
The Contractor shall submit the programme.

### Option A
If option A applies, review clause 1.3.
"""

    sections = parse_markdown_sections(markdown)

    assert [section.title for section in sections] == ["Main", "Clause 1", "Option A"]
    assert sections[2].heading_path == ["Main", "Clause 1", "Option A"]
    assert "review clause 1.3" in sections[2].content


def test_build_section_tree_nests_children():
    sections = parse_markdown_sections("# A\n\n## B\nText\n\n## C\nText")
    tree = build_section_tree(sections)

    assert len(tree) == 1
    assert tree[0].title == "A"
    assert [child.title for child in tree[0].children] == ["B", "C"]


def test_parse_markdown_without_headings_uses_document_section():
    sections = parse_markdown_sections("Plain extracted MinerU content.")

    assert sections[0].id == "section-001-document"
    assert sections[0].title == "Document"


def test_parse_mineru_content_sections_infers_numbered_hierarchy(tmp_path):
    content_list = [
        {"type": "text", "text": "Contents1 ", "text_level": 1, "page_idx": 2},
        {"type": "text", "text": "1 EXECUTIVE SUMMARY . 3 ", "page_idx": 2},
        {"type": "text", "text": "1 EXECUTIVE SUMMARY ", "text_level": 1, "page_idx": 3},
        {"type": "text", "text": "1.1 PURPOSE OF THE PRACTICE NOTES ", "text_level": 1, "page_idx": 3},
        {
            "type": "text",
            "text": "1.1.1 To cater for the wider adoption of NEC form in public works projects.",
            "page_idx": 3,
        },
        {"type": "text", "text": "1.2 KEY TOPICS OF THE PRACTICE NOTES ", "text_level": 1, "page_idx": 3},
        {"type": "text", "text": "a.Option Selection ", "text_level": 1, "page_idx": 3},
        {"type": "text", "text": "Considerations are included in Section A4.2.", "page_idx": 3},
    ]
    path = tmp_path / "sample_content_list.json"
    path.write_text(json.dumps(content_list), encoding="utf-8")

    sections = parse_mineru_content_sections(path)
    tree = build_section_tree(sections)

    assert [section.title for section in sections[:4]] == [
        "1 EXECUTIVE SUMMARY",
        "1.1 PURPOSE OF THE PRACTICE NOTES",
        "1.1.1 To cater for the wider adoption of NEC form in public works projects.",
        "1.2 KEY TOPICS OF THE PRACTICE NOTES",
    ]
    assert sections[0].level == 1
    assert sections[1].level == 2
    assert sections[2].level == 3
    assert sections[2].heading_path == [
        "1 EXECUTIVE SUMMARY",
        "1.1 PURPOSE OF THE PRACTICE NOTES",
        "1.1.1 To cater for the wider adoption of NEC form in public works projects.",
    ]
    assert tree[0].children[0].children[0].title.startswith("1.1.1")
    assert sections[-1].content == "Considerations are included in Section A4.2."


def test_parse_mineru_content_sections_preserves_media_and_tables(tmp_path):
    content_list = [
        {"type": "text", "text": "1 EXECUTIVE SUMMARY ", "text_level": 1},
        {"type": "text", "text": "1.1 PURPOSE ", "text_level": 1},
        {"type": "text", "text": "The matrix is shown below."},
        {
            "type": "chart",
            "img_path": "images/scatter.jpg",
            "sub_type": "scatter",
            "content": "| Point | Risk |\n|---|---|\n| A | Low |",
        },
        {
            "type": "table",
            "table_body": "<table><tr><td>Description</td><td>Value</td></tr></table>",
        },
    ]
    path = tmp_path / "sample_content_list.json"
    path.write_text(json.dumps(content_list), encoding="utf-8")

    sections = parse_mineru_content_sections(path)

    assert "[[MINERU_MEDIA|chart|scatter|images/scatter.jpg]]" in sections[-1].content
    assert "[[MINERU_TABLE_MD|scatter]]" in sections[-1].content
    assert "[[MINERU_TABLE_HTML]]" in sections[-1].content
    assert "<table><tr><td>Description</td><td>Value</td></tr></table>" in sections[-1].content
