# Plugin administration

Only administrators can install, update, enable, disable, retry, inspect diagnostics, revoke all grants, or uninstall plugins.

## Review rules

- Verify plugin ID, publisher, version, compatibility ranges, and dependencies.
- Deny capabilities without a clear, necessary rationale.
- Treat document/session reads as sensitive account data, session revocation as destructive, notification delivery as external disclosure, and `plugin.storage` secrets as write-only credentials.
- Treat signed/trusted, signed/unknown-key, signed/invalid, and unsigned states as distinct. An official catalogue listing is provenance, not cryptographic trust.
- Invalid signatures are blocked. Unsigned and unknown-key packages require explicit acknowledgement.
- Granting a highly privileged capability to an unsigned or unknown-key package additionally requires administrator password re-entry and a second explicit confirmation.
- Re-review permissions introduced by an update.

Permissions are shown as an expandable hierarchy. Approving a parent approves its requested subtree; approving a leaf does not grant its siblings. Required dependencies must already be installed at a compatible version. Available dependencies are shown as separate packages and must receive their own trust and permission review.

## Sources and updates

Uploads, direct URLs, and catalogue entries all use the same inspection and confirmation lifecycle. The official catalogue is enabled by default. Additional catalogue records retain their priority, enabled state, trust/provenance metadata, last successful check, and last error. Catalogue trust never bypasses package verification.

Installed URL/catalogue plugins retain source metadata for update checks. The update review shows release notes, dependency changes, and the exact permission delta before replacement. New permissions default to denied. Unverified updates inherit no prior grants and require every requested permission to be reviewed again. A discovered update can be reviewed and applied from its recorded source, and availability is also added to the existing administrator notification feed.

## Diagnostics and recovery

The Diagnostics tab shows process state, last exit code, and up to 200 structured events. Secret-, token-, password-, and webhook-shaped values are redacted. Disable a misbehaving plugin before investigating. Revocation blocks subsequent gateway calls; uninstall additionally removes package/private storage and provider registrations.

Production deployments must use bubblewrap isolation and a unique `PLUGIN_RUNTIME_TOKEN`. `NONBUBBLE_ENV=true` is development-only and must not be used for untrusted plugins.
