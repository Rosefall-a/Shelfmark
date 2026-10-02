# Plugin integration validation

Validation is split between the host repository and the independent plugin repository so neither side imports the other's private implementation.

## Host coverage

The application tests:

- manifest, compatibility, dependency, archive, digest, and publisher-trust validation;
- contextual installation consent, exact installation/user grants, revocation, and disabled-plugin rejection;
- runtime process isolation, private storage, frontend asset confinement, action mediation, structured diagnostics, and restart state;
- allowlisted sidebar/native extension contributions and sandboxed custom frontends;
- document ownership, path confinement, type/encoding/size rejection, and safe DTOs;
- minimized session listing and user-scoped revocation;
- provider registration, preference/grant checks, delivery results, retries, and cleanup.

## Plugin repository coverage

`Rosefall-a/unnamed_tracking_app_plugins` tests every manifest, permission rationale, source import boundary, frontend entry, package digest, and package validation rule. The three domain reference plugins additionally test exact public methods/capabilities, host confirmation declarations, namespaced provider registration, bounded delivery formatting, and absence of direct frontend network access.

Normal development builds are unsigned and intentionally exercise the untrusted-package warning. Release builds require the private reviewed signing key and fail closed when the signer is unavailable or out of scope.

## Cross-repository acceptance

For a release candidate:

1. Build the three `.utp` packages from the plugin repository.
2. Preview/install them through the application's real Plugin Manager.
3. Confirm denied permissions fail, approved permissions work, and revocation takes effect immediately.
4. Confirm sidebar pages disappear on disable/uninstall.
5. Exercise document missing/unsupported/oversized cases, session confirmation/revocation, and provider success/retry/disabled preference behavior.
6. Update a package, confirm consent does not broaden silently, and inspect redacted diagnostics.
7. Run both repositories' complete CI workflows and `mkdocs build --strict`.

See [Reference plugins](reference-plugins.md) and the [documentation review checklist](documentation-review.md).

## Repeatable repository lifecycle acceptance

`tools/check_plugin_repository_lifecycle.py` runs the current host against actual
packages built by a separate plugin checkout. Run it only against a disposable,
migrated PostgreSQL database with the backend requirements and the plugin
builder's `jsonschema` dependency installed:

```bash
python tools/check_plugin_repository_lifecycle.py \
  --plugins-root /path/to/unnamed_tracking_app_plugins \
  --work-root /tmp/plugin-acceptance
```

The work root must not exist. The runner downloads and inspects all live official
packages, creates signed releases with a disposable publisher registered only
inside its temporary test environment, and runs separate authenticated host and
runtime processes. It performs a real Jellyfin sync against a deterministic
Jellyfin HTTP server and verifies configuration, secrets and progress bytes
through restart, update, rollback and reinstall. It also checks permission
staging/revocation, release opt-out/opt-in, startup failure recovery, notifications,
retention, management-token scope isolation, confirmed purge and uninstall.
Only acquisition of the simulated release catalogue is substituted; the official
downloads, public gateway, runtime HTTP and workers are real.

Add `--browser` after building `src/frontend` and installing the plugin
repository's npm/Playwright dependencies to verify rendered catalogue filtering,
README, scope counts, risk bubbles, consent, duplicate choices, native UI and
Updates Available actions. `Plugin repository integration` runs this complete
acceptance in CI and retains logs and screenshots. The runtime deliberately
permits reduced isolation inside this disposable test environment and verifies
that the UI reports it accurately; real Bubblewrap namespace capability is
probed and the runtime unit suite also covers usable/unsupported policy behavior.
