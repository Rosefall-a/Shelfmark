# Document viewing

Game documents can be opened from a game's **Docs** tab.

## Supported documents

The viewer supports:

- **PDF** — displayed using the browser's native PDF viewer.
- **UTF-8 text** — common `.txt`, `.log`, `.csv`, `.json`, `.md`, `.ini`, `.cfg`, `.conf`, `.toml`, `.yaml/.yml`, `.xml`, `.properties` and related text MIME types.

HTML/XHTML are treated as text and returned as `text/plain`; they are **not rendered as HTML**. SVG and other active formats are not supported for inline viewing. Other document types remain downloadable.

## Use the viewer

1. Open a game.
2. Select **Docs**.
3. Open a document.
4. PDFs appear in the browser's native PDF viewer; supported text files appear in a read-only viewer.
5. Close the viewer to return to the document list.

The UI reports loading, missing/authorization, unsupported, server and network errors.

## Limitations and security

- Text documents must be valid UTF-8 and smaller than 5 MiB.
- Binary files are not interpreted as text.
- The browser-supplied MIME type is not trusted.
- The viewer uses the existing authenticated game-ownership check.
- Requested filenames must be a single filename component; path separators and traversal forms are rejected.
- Text is transported as `text/plain`, never as active HTML.
- PDFs are returned inline through the dedicated viewer endpoint.
- Responses use `X-Content-Type-Options: nosniff` and private, no-store caching.

This is a viewer, not a document-management or editing system.
