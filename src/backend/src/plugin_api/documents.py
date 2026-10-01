"""Safe, bounded representations of stored game documents for Plugin API v1.

Format policy follows application PR #241. No storage path crosses the gateway.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path
from urllib.parse import unquote

MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
MAX_CHUNK_BYTES = 24 * 1024
TEXT_EXTENSIONS = {
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
    ".markdown",
    ".rst",  # Existing Plugin API additions.
}
TEXT_MIME_TYPES = {
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
HTML_EXTENSIONS = {".html", ".htm", ".xhtml"}


class DocumentAccessError(ValueError):
    """Public document failure with a safe message and stable error category."""

    def __init__(self, kind: str, message: str, status_code: int):
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code

    def representation(self) -> dict:
        """Preserve explicit errors across the JSON action/route transport."""
        return {"error": {"kind": self.kind, "message": str(self), "status_code": self.status_code}}


def document_path(data_root: Path, user_id: object, folder: str | None, filename: str) -> Path:
    """Reject traversal, including stored/encoded separators and escaped symlinks."""
    decoded = unquote(filename)
    if (
        not filename
        or filename in {".", ".."}
        or decoded in {".", ".."}
        or any(char in filename + decoded for char in ("/", "\\", "\x00", ":"))
    ):
        raise DocumentAccessError("invalid", "Invalid document filename.", 400)
    if not folder:
        raise DocumentAccessError("missing", "Document not found.", 404)
    owner_root = (data_root / str(user_id) / "games").resolve()
    root = (owner_root / folder / "docs").resolve()
    path = (root / filename).resolve()
    try:
        root.relative_to(owner_root)
        path.relative_to(root)
    except ValueError as exc:
        raise DocumentAccessError("missing", "Document not found.", 404) from exc
    if not path.is_file():
        raise DocumentAccessError("missing", "Document not found.", 404)
    return path


def read_representation(path: Path) -> tuple[bytes, str, str, str]:
    """Read once, bounded even if the file grows; validate before returning any chunk."""
    try:
        with path.open("rb") as handle:
            signature = handle.read(5)
            is_pdf = signature == b"%PDF-"
            suffix = path.suffix.lower()
            guessed_type = mimetypes.guess_type(path.name)[0]
            if (
                not is_pdf
                and suffix not in TEXT_EXTENSIONS | HTML_EXTENSIONS
                and guessed_type not in TEXT_MIME_TYPES
            ):
                raise DocumentAccessError(
                    "unsupported", "This document format is not supported.", 415
                )
            data = signature + handle.read(MAX_DOCUMENT_BYTES + 1 - len(signature))
    except OSError as exc:
        raise DocumentAccessError("server", "Could not read document.", 500) from exc
    if len(data) > MAX_DOCUMENT_BYTES:
        raise DocumentAccessError("oversized", "Document exceeds the 5 MiB Plugin API limit.", 413)
    if is_pdf:
        media_type, document_format = "application/pdf", "pdf"
    else:
        if re.search(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", data):
            raise DocumentAccessError(
                "unsupported", "Binary files cannot be displayed as text.", 415
            )
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentAccessError(
                "unsupported", "Only UTF-8 text documents can be displayed.", 415
            ) from exc
        media_type = "text/plain"
        document_format = "html" if suffix in HTML_EXTENSIONS else "text"
    return data, media_type, document_format, hashlib.sha256(data).hexdigest()
