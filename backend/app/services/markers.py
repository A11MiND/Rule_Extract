from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentMarker:
    marker_type: str
    text: str
    start: int
    end: int
    color: str
    confidence: float = 1.0


RULE_REFERENCE_RE = re.compile(
    r"\b(?:Section\s+)?(?:[A-Z]\d+|\d+)(?:\.\d+){1,5}\b",
    re.I,
)

TEMPLATE_PLACEHOLDER_RE = re.compile(
    r"\[[^\]]*(?:insert|subject to review|HK\\?\$|_{2,}|two weeks|one month|12 months|12 weeks|365 days)[^\]]*\]",
    re.I,
)

BLANK_PLACEHOLDER_RE = re.compile(r"(?:HK\\?\$\s*)?_{2,}|\\_\s*\\_+")


def find_document_markers(text: str, doc_type: str) -> list[DocumentMarker]:
    """Find human-review markers by document role, not by specific template names."""
    if doc_type in {"template", "tender_submission"}:
        return find_template_markers(text)
    return find_rulebook_markers(text)


def find_rulebook_markers(text: str) -> list[DocumentMarker]:
    markers: list[DocumentMarker] = []
    for match in RULE_REFERENCE_RE.finditer(text):
        value = match.group(0)
        if _looks_like_page_or_year(value):
            continue
        markers.append(
            DocumentMarker(
                marker_type="reference",
                text=value,
                start=match.start(),
                end=match.end(),
                color="yellow",
                confidence=0.9,
            )
        )
    return _dedupe_overlaps(markers)


def find_template_markers(text: str) -> list[DocumentMarker]:
    markers: list[DocumentMarker] = []
    for pattern in (TEMPLATE_PLACEHOLDER_RE, BLANK_PLACEHOLDER_RE):
        for match in pattern.finditer(text):
            value = match.group(0)
            if _is_low_value_placeholder(value):
                continue
            markers.append(
                DocumentMarker(
                    marker_type="fillable",
                    text=value,
                    start=match.start(),
                    end=match.end(),
                    color="blue",
                    confidence=0.95,
                )
            )
    return _dedupe_overlaps(markers)


def marker_context(text: str, marker: DocumentMarker, before: int = 220, after: int = 260) -> str:
    return text[max(0, marker.start - before): marker.end + after]


def _dedupe_overlaps(markers: list[DocumentMarker]) -> list[DocumentMarker]:
    ordered = sorted(markers, key=lambda item: (item.start, -(item.end - item.start)))
    result: list[DocumentMarker] = []
    occupied: list[tuple[int, int]] = []
    for marker in ordered:
        if any(marker.start < end and marker.end > start for start, end in occupied):
            continue
        result.append(marker)
        occupied.append((marker.start, marker.end))
    return result


def _is_low_value_placeholder(value: str) -> bool:
    lower = value.lower()
    return "delete any row" in lower or len(value.strip()) < 2


def _looks_like_page_or_year(value: str) -> bool:
    normalized = value.replace("Section", "").strip()
    return bool(re.fullmatch(r"\d{4}(?:\.\d+)?", normalized))
