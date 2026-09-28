# Document viewer architecture

The viewer is intentionally layered on the existing game-document storage rather than introducing a second media store.

## Request flow

1. GameDetail.vue lists existing doc files through listGameFiles().
2. Clicking a document opens DocumentViewer.vue.
3. documentViewer.ts requests /api/game/{game_id}/files/doc/{filename}/view.
4. games.py authenticates the caller and resolves the game with _get_game_or_404(), scoped to the current user's game.
5. document_viewer.py validates the filename, checks the stored file, identifies PDF/text content, and constructs a safe response.

## MIME and format handling

PDFs are recognized by their %PDF- file signature and served as application/pdf with an inline content disposition so the browser can use its native viewer.

Text viewing uses a conservative extension/MIME allowlist. SVG remains excluded. HTML/XHTML are transported as text and sanitized before rendering; scripts, embeds, forms, media, external-resource tags, and inline styles are stripped. Text is decoded as UTF-8 and returned as text/plain.

The browser-supplied upload MIME type is not trusted by the viewer.

## Authorization and path safety

The endpoint is authenticated by the existing route dependency and calls _get_game_or_404(game_id, db, current_user.id). The file path is constructed only beneath that user's game directory.

The requested filename must be a single filename component. Path separators and traversal forms are rejected instead of being stripped.

The endpoint is separate from the generic download route. Existing generic game documents continue to download normally; only the dedicated viewer route returns an inline PDF/text response.

## Resource limits

Text files larger than 5 MiB are rejected before their contents are read. PDFs continue to use FileResponse so the server does not load the entire PDF into application memory.

## Adding another document type

1. Add type/signature checks to document_viewer.py.
2. Decide whether it is safe to return inline under the application's origin.
3. Add backend security/content tests.
4. Add a frontend result type and rendering branch.
5. Add frontend/browser/error tests and update the user guide.
6. Avoid a new dependency unless native browser support is demonstrably insufficient.
