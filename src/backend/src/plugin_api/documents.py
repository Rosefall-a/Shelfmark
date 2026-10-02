"""Safe, bounded representations of stored game documents for Plugin API v1.

Format policy follows application PR #241. No storage path crosses the gateway.
"""

from __future__ import annotations

import hashlib
import io
import mimetypes
import re
import zipfile
import zlib
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from src.database.models.game import Game
from src.database.models.game_file_item import GameFileItem

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
OFFICE_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".odp": "application/vnd.oasis.opendocument.presentation",
}
MAX_OFFICE_EXPANDED_BYTES = 20 * 1024 * 1024
MAX_OFFICE_XML_BYTES = 2 * 1024 * 1024


async def owned_document(
    db: AsyncSession, user_id: object, document_id: object
) -> tuple[GameFileItem, Game] | None:
    """Share the same persisted ownership boundary for reads and downloads."""
    row = (
        await db.execute(
            select(GameFileItem, Game)
            .options(raiseload("*"))
            .join(Game, Game.id == GameFileItem.game_id)
            .where(
                GameFileItem.id == document_id,
                GameFileItem.kind == "doc",
                GameFileItem.deleted_at.is_(None),
                Game.user_id == user_id,
                Game.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    return (row[0], row[1]) if row is not None else None


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


def read_representation(
    path: Path, max_bytes: int = MAX_DOCUMENT_BYTES
) -> tuple[bytes, str, str, str]:
    """Read and validate a document using the requested preview ceiling.

    max_bytes == 0 means unlimited for callers that explicitly opt in;
    legacy callers retain the original 5 MiB ceiling.
    """
    if type(max_bytes) is not int or max_bytes < 0:
        raise DocumentAccessError("invalid", "Invalid document size limit.", 400)
    try:
        with path.open("rb") as handle:
            signature = handle.read(5)
            is_pdf = signature == b"%PDF-"
            suffix = path.suffix.lower()
            guessed_type = mimetypes.guess_type(path.name)[0]
            if (
                not is_pdf
                and suffix not in TEXT_EXTENSIONS | HTML_EXTENSIONS | OFFICE_TYPES.keys()
                and guessed_type not in TEXT_MIME_TYPES
            ):
                raise DocumentAccessError(
                    "unsupported", "This document format is not supported.", 415
                )
            if max_bytes == 0:
                data = signature + handle.read()
            else:
                data = signature + handle.read(max_bytes + 1 - len(signature))
    except OSError as exc:
        raise DocumentAccessError("server", "Could not read document.", 500) from exc
    if max_bytes and len(data) > max_bytes:
        raise DocumentAccessError(
            "oversized", "Document exceeds the configured Plugin API preview limit.", 413
        )
    if is_pdf:
        media_type, document_format = "application/pdf", "pdf"
    elif suffix in OFFICE_TYPES:
        validate_office_archive(data, suffix)
        media_type, document_format = OFFICE_TYPES[suffix], suffix[1:]
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


def validate_office_archive(data: bytes, suffix: str) -> None:
    """Validate bounded, inactive office containers; never extract them to disk."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > 1024:
                raise ValueError("too many archive entries")
            names: set[str] = set()
            total = 0
            for entry in entries:
                name = unquote(entry.filename).replace("\\", "/")
                parts = name.lower().split("/")
                if (
                    name.startswith("/")
                    or ":" in name
                    or "\x00" in name
                    or ".." in parts
                    or name.casefold() in names
                    or entry.flag_bits & 1
                    or entry.compress_type not in {0, 8}
                    or "vbaproject.bin" in parts
                    or "basic" in parts
                    or "scripts" in parts
                    or "embeddings" in parts
                    or "activex" in parts
                    or (entry.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise ValueError("unsafe or active archive entry")
                names.add(name.casefold())
                total += entry.file_size
                limit = (
                    MAX_OFFICE_XML_BYTES
                    if name.lower().endswith((".xml", ".rels"))
                    else MAX_DOCUMENT_BYTES
                )
                if (
                    entry.file_size > limit
                    or total > MAX_OFFICE_EXPANDED_BYTES
                    or entry.file_size > max(1024, entry.compress_size * 100)
                ):
                    raise ValueError("office expansion limit")
                with archive.open(entry) as handle:
                    content = handle.read(limit + 1)
                if len(content) != entry.file_size:
                    raise ValueError("invalid archive size")
                if name.lower().endswith((".xml", ".rels")):
                    # Decode before checking declarations: UTF-16 must not evade the DTD guard.
                    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
                        xml = content.decode("utf-16")
                    else:
                        xml = content.decode("utf-8-sig")
                    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", xml, re.IGNORECASE):
                        raise ValueError("XML entities are unsupported")
                    tree = ElementTree.fromstring(xml)
                    if sum(1 for _ in tree.iter()) > 50_000:
                        raise ValueError("too many XML nodes")
                    if name.lower() == "[content_types].xml" and "macroenabled" in xml.lower():
                        raise ValueError("macros are unsupported")
                    if any(
                        node.tag.rsplit("}", 1)[-1]
                        in {"script", "event-listener", "encryption-data"}
                        for node in tree.iter()
                    ):
                        raise ValueError("active office content")
            if suffix in {".odt", ".odp"}:
                if archive.read("mimetype").decode() != OFFICE_TYPES[suffix]:
                    raise ValueError("incorrect OpenDocument type")
                required = "content.xml"
            else:
                required = "word/document.xml" if suffix == ".docx" else "ppt/presentation.xml"
                if "[content_types].xml" not in names:
                    raise ValueError("missing content types")
            if required not in names:
                raise ValueError("missing main document")
    except (
        ValueError,
        KeyError,
        OSError,
        RuntimeError,
        zipfile.BadZipFile,
        zlib.error,
        ElementTree.ParseError,
    ) as exc:
        raise DocumentAccessError(
            "unsupported",
            "This office document is malformed, encrypted, active, or exceeds safe preview limits.",
            415,
        ) from exc
