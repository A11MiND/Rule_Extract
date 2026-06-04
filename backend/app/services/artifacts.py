from __future__ import annotations

import shutil
import ipaddress
import socket
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from urllib.parse import urlparse

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
        extract_root = extract_dir.resolve()
        total_uncompressed = 0
        for member in archive.infolist():
            normalized = PurePosixPath(member.filename.replace("\\", "/"))
            member_path = (extract_root / normalized).resolve()
            try:
                member_path.relative_to(extract_root)
            except ValueError:
                raise ValueError(f"Archive contains an unsafe path: {member.filename}")
            unix_mode = member.external_attr >> 16
            if unix_mode and (unix_mode & 0o170000) == 0o120000:
                raise ValueError(f"Archive contains a symbolic link: {member.filename}")
            total_uncompressed += member.file_size
            if total_uncompressed > 500 * 1024 * 1024:
                raise ValueError("Archive exceeds the 500 MB extraction limit.")
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
    _validate_external_url(pdf_url)
    path = source_pdf_path(document_id, storage_root)
    try:
        with requests.get(pdf_url, timeout=60, stream=True, allow_redirects=False) as response:
            if 300 <= response.status_code < 400:
                raise ValueError("Source PDF URL redirects are not supported.")
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if content_type and "pdf" not in content_type and "octet-stream" not in content_type:
                raise ValueError("Source URL did not return a PDF.")
            content_length = int(response.headers.get("content-length") or 0)
            if content_length > 100 * 1024 * 1024:
                raise ValueError("Source PDF exceeds the 100 MB intake limit.")
            total = 0
            with path.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > 100 * 1024 * 1024:
                        raise ValueError("Source PDF exceeds the 100 MB intake limit.")
                    output.write(chunk)
            if total == 0:
                raise ValueError("Source PDF response was empty.")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def _validate_external_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only public HTTP(S) PDF URLs are supported.")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, port)}
    except (socket.gaierror, ValueError) as exc:
        raise ValueError("Source URL hostname could not be resolved.") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("Source URL must resolve only to public Internet addresses.")
