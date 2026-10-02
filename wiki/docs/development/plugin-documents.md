# Scoped document API

`documents.list` and `documents.read` v1 require the live `documents.read` grant. The host owns the user/installation context, `GameFileItem` lookup, active-game ownership, deleted/kind filtering and filesystem confinement. Plugins receive DTOs and base64 content; they never receive storage paths, cookies or ORM objects.

This additive contract supports the official Scoped Document Viewer implementation of PR #241. The original unchunked response stays compatible, including its legacy `text/html` representation. New viewers must request bounded chunks and sanitize HTML explicitly. No runtime limits or capability enforcement were relaxed.

## Listing

Payload: `{limit: 32, offset: 0}`. Ordering is game sort title, stored filename and document ID. Returns `{documents: [...], next_offset: integer | null}`. An offset opts into paginated, bounded responses; metadata is capped below 48 KiB using ASCII-escaped JSON sizing, leaving room under the runtime's 64 KiB output limit. Missing/unsafe stored paths are skipped. The continuation offset counts scanned rows, including skipped rows. Pagination is a fresh query, not a persistent snapshot; concurrent library changes can alter page ordering.

Metadata fields remain `id`, `game_id`, `game_title`, `filename`, `media_type`, `size_bytes`, `created_at`. Listing MIME is an informational guess; it is never authorization to render a document. Only read-time validated MIME/format is authoritative.

## Reading

Payload: `{document_id: UUID, chunk_bytes: 24576, offset: 0}`. Later requests add `content_sha256` from the first response and use the previous `next_offset`. Chunk size must be 1–24576 bytes, offsets must be integers within the file, and bool values are rejected. Every chunk repeats the actual ownership lookup and live grant check.

Success fields:

- `document`: authoritative DTO, with size from the validated bytes and validated MIME.
- `encoding: base64`, `content`: at most 24 KiB before base64 encoding.
- `format: pdf | text | html | docx | pptx | odt | odp`. HTML is transported with `document.media_type: text/plain`.
- `offset`, `next_offset`, `complete`: exact byte-range accounting, including empty files.
- `content_sha256`: SHA-256 of the complete validated file. A continuation without the matching digest returns a changed-document error. Consumers should recheck the assembled digest.

The host reads once per request, at most 5 MiB plus a sentinel byte, before disclosing any chunk. It validates the whole text and computes its digest each time. It does not retain shared user-content caches or reusable authorization tokens. This trades repeated bounded reads for simple revocation and consistency semantics.

Domain failures return `{error: {kind, message, status_code}}` inside the gateway payload, so action/SDK transports preserve explicit errors. Kinds include invalid (400), missing (404), changed (409), oversized (413), unsupported (415) and server (500). Namespaced plugin handlers may promote the domain status to HTTP. Missing and another user's IDs are indistinguishable. Runtime-token, installation/lifecycle and grant failures remain host HTTP errors; they are not converted to successful domain reads. The frontend bridge includes the failing action's HTTP `status_code` without sharing credentials or raw response bodies.

## Format and security policy

PDF `%PDF-` signature takes precedence over filename, matching PR #241. Text uses the PR's extension/MIME allowlist, strict UTF-8 and rejection of binary controls, with existing `.markdown`/`.rst` API additions retained. HTML/HTM/XHTML is bounded validated text with a format hint; sanitization remains the consumer's duty. SVG and unsupported types are rejected. Text/HTML scripts are never returned as an executable page. Successful gateway, action and namespaced route JSON responses use `X-Content-Type-Options: nosniff` and `Cache-Control: private, no-store`.

Raw and decoded filename separators, dot traversal, NUL and Windows drive syntax are rejected. Resolved document and game-folder paths must remain within the owner's games/document directories. Escaping symlinks are rejected. No caller-supplied file path is accepted.

The platform's existing 5 MiB cap also applies to PDF. PR #241 streamed PDFs without a viewer cap; unrestricted PDF streaming is not reproduced by this bounded API. The official sandbox viewer bundles PDF.js because native PDF plugins cannot reliably run under `allow-scripts` alone. No same-origin, native, network or worker privilege is added.

## Verification

`tests/test_plugin_documents.py` exercises real SQL/HTTP ownership and grants, another user's row, unknown/trashed/non-doc rows, unauthorized entrypoints, stored traversal, long Unicode metadata pagination, exact-limit chunk reassembly, replacement and revocation. Format fixtures reproduce PR #241's actual behavior; external `tools/check_document_parity.py` in the plugin repository also compares both actual source implementations. The plugin's browser tests verify sanitization, literal text and sandbox PDF rendering rather than treating byte equivalence as sufficient security evidence.

## Game Docs reader contributions

A UI document may declare `document_readers: [{id: "reader", page_id: "documents", label: "Read", extensions: ["*"], order: 0}]`. Extensions are lowercase suffixes such as `.pdf`, or `*`. Both live `documents.read` and `frontend.context.documents` grants are required. Readers reference an existing page and are selected deterministically by order, plugin ID and contribution ID. Disabled/revoked installations lose their contribution. The host game Docs list supplies an opaque indexed document ID, opens the matching page in a new tab, and retains a separate original download link. Without a reader, existing filename download behavior remains.

`plugin.context` gives the sandbox `document_id` and `game_id` from the page query. Context is a navigation hint, not authorization: every read still performs ownership/grant checks. The optional library page can remain accessible without registering sidebar navigation.

## Original downloads

`plugin.download-document` accepts `{document_id: UUID}`. The parent verifies the authenticated scoped HEAD endpoint before starting a browser download. GET/HEAD `/api/plugins/{plugin_id}/capabilities/documents/{document_id}/download` repeat installation, live `documents.read`, ownership/kind/deletion and safe stored-path checks. The response streams the original with attachment disposition, `application/octet-stream`, `nosniff` and private/no-store. Preview size/format limits do not prevent original download. Credentials and raw download URLs are never sent to the opaque sandbox.

## Office/OpenDocument reading previews

DOCX/PPTX/ODT/ODP are additive supported formats, using authoritative Office MIME types. Before any chunk is disclosed, the host validates the complete ZIP: at most 1,024 entries, 20 MiB expanded total, 2 MiB per XML part, 5 MiB per other part, and 100:1 expansion with a 1 KiB floor. Encryption, macros, ActiveX, embedded objects, symlinks, escaping/duplicate paths, invalid CRC/ZIP/XML, XML DTDs/entities and active script/event content are rejected with 415. UTF-16 XML is decoded before declaration checks. The existing 5 MiB input cap applies.

The official plugin constructs inert text/basic tables and bounded PNG/JPEG images, preserving slide order. It never executes document markup, uploaded styles or external relationships. Complex layout, charts, animations and equations require the downloadable original. Legacy DOC/PPT and macro-enabled Office remain unsupported.
