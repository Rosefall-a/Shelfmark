from pathlib import Path

import pytest
from fastapi import HTTPException

from src.helpers.document_viewer import (
    MAX_TEXT_VIEW_BYTES,
    document_original_filename,
    document_view_response,
    safe_document_filename,
)


def test_safe_document_filename_rejects_path_traversal() -> None:
    for name in ("../secret.txt", r"..\secret.txt", "/tmp/secret.txt", "a/b.txt"):
        with pytest.raises(HTTPException) as exc:
            safe_document_filename(name)
        assert exc.value.status_code == 400


def test_document_original_filename_removes_dedupe_prefix() -> None:
    assert document_original_filename("abcdefgh_manual.pdf") == "manual.pdf"


def test_pdf_response_requires_pdf_signature(tmp_path: Path) -> None:
    path = tmp_path / "abcdefgh_manual.pdf"
    path.write_bytes(b"%PDF-1.7\n% fixture")
    response = document_view_response(path, path.name)

    assert response.media_type == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_pdf_with_wrong_extension_is_still_safe_to_view(tmp_path: Path) -> None:
    path = tmp_path / "abcdefgh_manual.bin"
    path.write_bytes(b"%PDF-1.7\n% fixture")
    response = document_view_response(path, path.name)

    assert response.media_type == "application/pdf"


def test_html_and_svg_are_never_viewable(tmp_path: Path) -> None:
    for suffix, content in ((".html", b"<script>alert(1)</script>"), (".svg", b"<svg/>")):
        path = tmp_path / f"abcdefgh_file{suffix}"
        path.write_bytes(content)
        with pytest.raises(HTTPException) as exc:
            document_view_response(path, path.name)
        assert exc.value.status_code == 415


def test_text_is_returned_as_plain_text(tmp_path: Path) -> None:
    path = tmp_path / "abcdefgh_notes.txt"
    path.write_text("<script>alert(1)</script>\nhello", encoding="utf-8")
    response = document_view_response(path, path.name)

    assert response.media_type == "text/plain"
    assert b"<script>" in response.body
    assert response.headers["content-disposition"].startswith("inline;")


def test_binary_text_candidate_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "abcdefgh_data.txt"
    path.write_bytes(b"hello\x00world")
    with pytest.raises(HTTPException) as exc:
        document_view_response(path, path.name)
    assert exc.value.status_code == 415


def test_non_utf8_text_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "abcdefgh_notes.txt"
    path.write_bytes("café".encode("latin-1"))
    with pytest.raises(HTTPException) as exc:
        document_view_response(path, path.name)
    assert exc.value.status_code == 415


def test_large_text_is_rejected_without_rendering(tmp_path: Path) -> None:
    path = tmp_path / "abcdefgh_large.txt"
    path.write_bytes(b"x" * (MAX_TEXT_VIEW_BYTES + 1))
    with pytest.raises(HTTPException) as exc:
        document_view_response(path, path.name)
    assert exc.value.status_code == 413


def test_missing_document_is_404(tmp_path: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        document_view_response(tmp_path / "missing.txt", "missing.txt")
    assert exc.value.status_code == 404
