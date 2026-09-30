# Documentation review checklist

Use this checklist for every user-visible change and before a release.

## Evidence

- Identify the owning route, service, component, migration, or public contract.
- Describe only behavior present in the target branch; identify optional deployment configuration explicitly.
- Check role and user scope, destructive behavior, limits, error handling, backup implications, and secret handling.
- Update navigation and nearby cross-links when adding or moving a page.

## Verification

- Follow setup/user/admin instructions against a clean or representative deployment.
- Verify API names and examples against current routes/contracts.
- For plugins, test package preview, consent, install, enable, action dispatch, revocation, disable, update, diagnostics, and uninstall through the public boundary.
- Run `mkdocs build --strict` from `wiki/`.
- Run the code test/lint/type workflows relevant to the documented behavior.

## Review record

The Phase 2 audit replaced placeholder user/admin/integration pages, reconciled Plugin API v1 capabilities and consent, documented the notification coordinator and three external reference plugins, and added strict MkDocs CI. Future pull requests should name the pages checked in their testing section.
