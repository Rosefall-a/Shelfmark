# Document viewing

Game documents can be opened directly from a game's **Docs** tab.

## Supported documents

The viewer currently supports:
- **PDF** — opened using the browser's built-in PDF viewer.
- **HTML/XHTML** — sanitized before rendering.
- **UTF-8 text** — common plain-text formats such as .txt, .log, .csv, .json, .md, .ini, .cfg, .conf, .toml, .yaml/.yml, .xml, and .properties.

Other document types remain downloadable through the existing file storage but are not rendered by the viewer.

## How it works

1. Open a game and select **Docs**.
2. Select **View** if necessary.
3. Click a document filename.
4. PDFs appear in the browser's native PDF viewer. Text documents appear in a read-only, scrollable text area.
5. Close the viewer to return to the Docs list.

## Limitations

- Text documents must be valid UTF-8 and smaller than 5 MiB for in-app viewing.
- Binary files are not interpreted as text.
- HTML, SVG, and other active web document formats are deliberately not rendered.
- PDF rendering depends on the browser's PDF support.
- This feature is a viewer, not a document-management or editing system.

## Security behavior

Document viewing uses the same authenticated game ownership check as the existing game file endpoints. A user cannot use the viewer to access another user's game files.

The server rejects path separators in the requested stored filename rather than normalizing them, preventing path-traversal attempts.

All viewer responses use text/plain transport except PDFs. HTML/XHTML are marked with X-Document-Format: html and sanitized with DOMPurify before insertion; raw uploaded HTML is never served as a navigable HTML document. SVG is excluded. Responses also use X-Content-Type-Options: nosniff and private, non-persistent caching.
