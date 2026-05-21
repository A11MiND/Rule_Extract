from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
FRONT_MATTER_HEADING_RE = re.compile(r"^(nec|practice notes|development bureau|contents)\b", re.I)
NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)(?:\.|\s+)(.*)$")
PART_HEADING_RE = re.compile(r"^(PART\s+[A-Z])\b", re.I)
LETTERED_HEADING_RE = re.compile(r"^([a-z])\.\s*(.+)$", re.I)
ALPHA_NUMBERED_HEADING_RE = re.compile(r"^([A-Z])(\d+)(?:\.(\d+))*\s+(.+)$")


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


def parse_mineru_content_sections(content_list_path: Path) -> list[ParsedSection]:
    data = json.loads(content_list_path.read_text(encoding="utf-8"))
    sections: list[ParsedSection] = []
    path_by_level: dict[int, str] = {}
    seen: dict[str, int] = {}
    started_body = False

    for item in data:
        item_type = item.get("type")
        if item_type not in {"text", "list", "table", "image", "chart"}:
            continue

        if item_type in {"table", "image", "chart"}:
            if not started_body or not sections:
                continue
            block = normalize_mineru_media(item)
            if block:
                sections[-1].content = append_content(sections[-1].content, block)
            continue

        text = normalize_mineru_text(item)
        if not text:
            continue

        level = infer_mineru_heading_level(text, item.get("text_level"), path_by_level)
        if not started_body:
            if not is_body_start(text, item.get("text_level")):
                continue
            started_body = True

        if level:
            title = trim_section_title(text)
            position = len(sections) + 1
            heading_path = update_heading_path(path_by_level, level, title)
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
                    content=text if is_clause_paragraph_heading(text, item.get("text_level")) else "",
                )
            )
            continue

        if sections:
            sections[-1].content = append_content(sections[-1].content, text)

    return sections


def normalize_mineru_media(item: dict) -> str:
    item_type = str(item.get("type") or "")
    parts: list[str] = []
    image_path = str(item.get("img_path") or "").strip()
    subtype = str(item.get("sub_type") or "").strip() or item_type

    if image_path:
        parts.append(f"[[MINERU_MEDIA|{item_type}|{subtype}|{image_path}]]")

    if item_type == "table":
        table_body = str(item.get("table_body") or "").strip()
        if table_body:
            parts.append(f"[[MINERU_TABLE_HTML]]\n{table_body}\n[[/MINERU_TABLE_HTML]]")
    elif item_type == "chart":
        content = str(item.get("content") or "").strip()
        if content:
            parts.append(f"[[MINERU_TABLE_MD|{subtype}]]\n{content}\n[[/MINERU_TABLE_MD]]")

    return "\n\n".join(parts)


def normalize_mineru_text(item: dict) -> str:
    if item.get("type") == "list":
        list_items = item.get("list_items")
        if isinstance(list_items, list):
            return "\n".join(f"- {str(list_item).strip()}" for list_item in list_items if str(list_item).strip())
    text = item.get("text") or ""
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text


def is_body_start(text: str, text_level: int | None) -> bool:
    return text_level == 1 and bool(re.match(r"^1\s+[A-Z]", text))


def infer_mineru_heading_level(
    text: str, text_level: int | None, path_by_level: dict[int, str]
) -> int | None:
    cleaned = trim_section_title(text)
    if is_toc_line(text):
        return None

    part_match = PART_HEADING_RE.match(cleaned)
    if part_match:
        return 1

    alpha_match = ALPHA_NUMBERED_HEADING_RE.match(cleaned)
    if alpha_match:
        dot_count = cleaned.split()[0].count(".")
        return min(6, 2 + dot_count)

    numbered_match = NUMBERED_HEADING_RE.match(cleaned)
    if numbered_match:
        number = numbered_match.group(1)
        return min(6, number.count(".") + 1)

    lettered_match = LETTERED_HEADING_RE.match(cleaned)
    if lettered_match:
        if path_by_level:
            deepest_level = max(path_by_level)
            if LETTERED_HEADING_RE.match(path_by_level[deepest_level]):
                return deepest_level
            return min(6, deepest_level + 1)
        return 1

    if text_level == 1 and not FRONT_MATTER_HEADING_RE.match(cleaned):
        current_parent = max(path_by_level) if path_by_level else 1
        return min(6, current_parent + 1)

    return None


def is_toc_line(text: str) -> bool:
    return bool(re.search(r"\.{2,}\s*\d+\s*$", text) or re.search(r"\s\.\s*\d+\s*$", text))


def trim_section_title(text: str) -> str:
    title = re.sub(r"\s+", " ", text).strip()
    title = re.sub(r"\s*\.{2,}\s*\d+\s*$", "", title)
    title = re.sub(r"\s+\.\s*\d+\s*$", "", title)
    return title[:180]


def is_clause_paragraph_heading(text: str, text_level: int | None) -> bool:
    if text_level is not None:
        return False
    return bool(NUMBERED_HEADING_RE.match(text) or ALPHA_NUMBERED_HEADING_RE.match(text))


def update_heading_path(path_by_level: dict[int, str], level: int, title: str) -> list[str]:
    path_by_level[level] = title
    for stale_level in list(path_by_level):
        if stale_level > level:
            del path_by_level[stale_level]
    return [path_by_level[key] for key in sorted(path_by_level) if key <= level]


def append_content(existing: str, text: str) -> str:
    if not existing:
        return text
    return f"{existing}\n\n{text}"


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
