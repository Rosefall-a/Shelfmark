# Document viewer architecture

The viewer reuses the existing game-document storage and authorization model.

## Request flow

1. Game detail lists existing `doc` files.
2. The user selects a document.
3. The frontend requests `/api/game/{game_id}/files/doc/{filename}/view`.
4. The backend authenticates the current user and resolves the game through the existing ownership-scoped lookup.
5. `document_viewer.py` validates the filename, checks the stored file and determines whether it is a PDF or supported UTF-8 text.

## Content handling

PDFs are identified by their `%PDF-` signature and returned as `application/pdf` with inline disposition.

Text formats use an extension/MIME allowlist. HTML/XHTML may be classified as text but are returned as `text/plain`; they are not sanitized and rendered as HTML. SVG is excluded.

Text is read only after a 5 MiB size check and must be valid UTF-8 without binary control bytes.

## Security

The viewer uses the existing authenticated game ownership check. The requested filename must not contain path separators or traversal after URL decoding.

The dedicated viewer route is separate from generic download behavior. Unsupported formats continue to download normally.

## Extending the viewer

A new format requires a safe content check, an explicit decision that inline rendering is safe under the application's origin, backend security/resource tests, a frontend rendering branch and documentation. Avoid a new dependency when native browser support is sufficient.
