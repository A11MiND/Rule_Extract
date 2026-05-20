from backend.app.services.markdown import build_section_tree, parse_markdown_sections


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
