from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass
class ParsedSection:
    id: str
    position: int
    level: int
    title: str
    heading_path: list[str]
    content: str
    children: list["ParsedSection"] = field(default_factory=list)


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized.lower()).strip("-")
    return slug or "section"


def parse_markdown_sections(markdown: str) -> list[ParsedSection]:
    lines = markdown.splitlines()
    heading_indexes: list[tuple[int, int, str]] = []

    for index, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if match:
            heading_indexes.append((index, len(match.group(1)), match.group(2).strip()))

    if not heading_indexes:
        content = markdown.strip()
        return [
            ParsedSection(
                id="section-001-document",
                position=1,
                level=1,
                title="Document",
                heading_path=["Document"],
                content=content,
            )
        ]

    sections: list[ParsedSection] = []
    path_by_level: dict[int, str] = {}
    seen: dict[str, int] = {}

    for position, (line_index, level, title) in enumerate(heading_indexes, start=1):
        next_line_index = heading_indexes[position][0] if position < len(heading_indexes) else len(lines)
        body_lines = lines[line_index + 1 : next_line_index]
        body = "\n".join(body_lines).strip()
        path_by_level[level] = title
        for stale_level in list(path_by_level):
            if stale_level > level:
                del path_by_level[stale_level]
        heading_path = [path_by_level[key] for key in sorted(path_by_level) if key <= level]
        base = f"section-{position:03d}-{slugify('-'.join(heading_path))}"
        seen[base] = seen.get(base, 0) + 1
        section_id = base if seen[base] == 1 else f"{base}-{seen[base]}"
        sections.append(
            ParsedSection(
                id=section_id,
                position=position,
                level=level,
                title=title,
                heading_path=heading_path,
                content=body,
            )
        )

    return sections


def build_section_tree(sections: list[ParsedSection]) -> list[ParsedSection]:
    roots: list[ParsedSection] = []
    stack: list[ParsedSection] = []

    for section in sections:
        section.children = []
        while stack and stack[-1].level >= section.level:
            stack.pop()
        if stack:
            stack[-1].children.append(section)
        else:
            roots.append(section)
        stack.append(section)

    return roots


def section_window(sections: list[ParsedSection], index: int, neighbor_count: int = 1) -> str:
    start = max(0, index - neighbor_count)
    end = min(len(sections), index + neighbor_count + 1)
    chunks: list[str] = []
    for section in sections[start:end]:
        heading = "#" * section.level + " " + section.title
        chunks.append(f"{heading}\n{section.content}".strip())
    return "\n\n".join(chunks)
