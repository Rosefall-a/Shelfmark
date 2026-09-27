"""Safety checks and response helpers for the small document viewer.

This module deliberately supports only browser-safe PDF files and UTF-8 text.
It does not provide a general-purpose file previewer.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import HTTPException, status
from fastapi.responses import FileResponse, PlainTextResponse, Response

MAX_TEXT_VIEW_BYTES = 5 * 1024 * 1024

# These formats are intentionally plain-text only. HTML/SVG and other active
# document formats are excluded even when they contain text.
_TEXT_EXTENSIONS = {
    ".cfg",
    ".conf",
    ".csv",
    ".ini",
    ".json",
    ".log",
    ".md",
    ".nfo",
    ".properties",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

_TEXT_MIME_TYPES = {
    "application/json",
    "application/ld+json",
    "application/xml",
    "application/yaml",
    "text/csv",
    "text/markdown",
    "text/plain",
    "text/xml",
    "text/yaml",
}


def safe_document_filename(filename: str) -> str:
    """Return a filename only if it cannot escape the selected media folder."""
    if not filename or filename in {".", ".."}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid document filename.",
        )

    # Reject traversal instead of silently normalising it away. Backslashes
    # are rejected too so the check remains safe if storage is ever hosted on
    # a Windows filesystem.
    decoded_filename = unquote(filename)
    if (
        "/" in filename
        or "\\" in filename
        or "/" in decoded_filename
        or "\\" in decoded_filename
        or Path(filename).name != filename
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path traversal is not allowed.",
        )

    return filename


def document_original_filename(filename: str) -> str:
    """Remove the upload dedupe prefix used by save_media_bytes."""
    safe_document_filename(filename)
    return filename.split("_", 1)[-1]


def _is_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(5) == b"%PDF-"
    except OSError:
        return False


def _is_utf8_text(path: Path) -> str:
    """Read a bounded UTF-8 text file, rejecting binary/oversized content."""
    try:
        if path.stat().st_size > MAX_TEXT_VIEW_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Text document is too large to view in the browser.",
            )
        data = path.read_bytes()
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read document.",
        ) from exc

    if any(byte < 32 and byte not in {9, 10, 13} for byte in data):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Binary files cannot be displayed as text.",
        )

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only UTF-8 text documents can be displayed.",
        ) from exc


def _looks_like_text_document(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm", ".svg", ".xhtml"}:
        return False
    mime_type = mimetypes.guess_type(path.name)[0]
    return suffix in _TEXT_EXTENSIONS or mime_type in _TEXT_MIME_TYPES


def document_view_response(
    path: Path, filename: str, allowed_root: Path | None = None
) -> Response:
    """Validate and build the response for the document viewer endpoint."""
    safe_document_filename(filename)
    if allowed_root is not None:
        try:
            path.resolve(strict=False).relative_to(allowed_root.resolve(strict=False))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found.",
            ) from exc
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    original_name = document_original_filename(filename)
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }

    if _is_pdf(path):
        return FileResponse(
            path,
            filename=original_name,
            media_type="application/pdf",
            content_disposition_type="inline",
            headers=headers,
        )

    if not _looks_like_text_document(path):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="This document format is not supported by the viewer.",
        )

    content = _is_utf8_text(path)
    return PlainTextResponse(
        content=content,
        media_type="text/plain",
        headers={
            **headers,
            "Content-Disposition": "inline; filename*=UTF-8''" + quote(original_name, safe="!#$&+-.^_|~"),
        },
    )
