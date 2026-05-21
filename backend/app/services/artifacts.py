from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import requests

from ..config import settings


def document_storage_dir(document_id: int, storage_root: Path | None = None) -> Path:
    root = (storage_root or settings.storage_root) / "documents" / str(document_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def write_zip(document_id: int, content: bytes, storage_root: Path | None = None) -> Path:
    path = document_storage_dir(document_id, storage_root) / "mineru-result.zip"
    path.write_bytes(content)
    return path


def extract_zip(document_id: int, zip_path: Path, storage_root: Path | None = None) -> dict:
    extract_dir = document_storage_dir(document_id, storage_root) / "mineru"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(extract_dir)

    markdown_files = sorted(extract_dir.rglob("*.md"), key=lambda path: path.stat().st_size, reverse=True)
    json_files = sorted(extract_dir.rglob("*.json"))
    markdown_path = pick_markdown_file(markdown_files)
    source_pdf = pick_source_pdf(extract_dir)

    return {
        "extract_dir": str(extract_dir),
        "markdown_path": str(markdown_path) if markdown_path else None,
        "source_pdf_path": str(source_pdf) if source_pdf else None,
        "json_paths": [str(path) for path in json_files],
        "files": [str(path) for path in sorted(extract_dir.rglob("*")) if path.is_file()],
    }


def pick_markdown_file(markdown_files: list[Path]) -> Path | None:
    if not markdown_files:
        return None
    for path in markdown_files:
        if path.name.lower() in {"full.md", "full_text.md", "document.md"}:
            return path
    return markdown_files[0]


def pick_source_pdf(extract_dir: Path) -> Path | None:
    pdf_files = sorted(extract_dir.rglob("*.pdf"))
    if not pdf_files:
        return None
    for path in pdf_files:
        if path.name.lower().endswith("_origin.pdf") or path.name.lower() == "origin.pdf":
            return path
    return pdf_files[0]


def source_pdf_path(document_id: int, storage_root: Path | None = None) -> Path:
    return document_storage_dir(document_id, storage_root) / "source.pdf"


def download_source_pdf(document_id: int, pdf_url: str, storage_root: Path | None = None) -> Path:
    path = source_pdf_path(document_id, storage_root)
    response = requests.get(pdf_url, timeout=60)
    response.raise_for_status()
    path.write_bytes(response.content)
    return path
