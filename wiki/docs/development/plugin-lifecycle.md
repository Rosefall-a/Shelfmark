# Plugin Manager lifecycle

The host backend owns the installed inventory. It persists identity, version, source, digest, publisher trust, enabled preference, runtime observations, staged releases and update policy. PostgreSQL owns permission decisions and installation-scoped grants. The runtime owns packages, retained versions, configuration, storage, secrets and process state. The frontend reads this inventory; a temporarily unavailable runtime does not make an installed plugin disappear. Its current health is reported as unknown until observations resume.

## Operations and data

| Operation | Package behavior | Plugin-owned data |
| --- | --- | --- |
| Install | Validate, review permissions, create installation identity, start and check health | Create a namespace |
| Configure/approve | Review declared scopes; configure through the plugin's own application page | Preserve |
| Enable | Enable and start the installed package | Preserve |
| Start | Start an enabled, stopped package | Preserve |
| Stop | Stop execution while retaining enablement; remain stopped after restart | Preserve |
| Disable | Stop execution and persist disabled preference | Preserve, including grants and secrets |
| Update | Validate/stage a newer release, approve new scopes, switch and verify | Preserve |
| Rollback | Switch to a retained package, verify and retain its predecessor | Preserve |
| Reinstall | Revalidate and replace the exact installed version/digest; never follow a newer URL release | Preserve |
| Reinstall with purge | Explicit confirmation, erase owned state and grants, replace exact package | Purge |
| Uninstall | Stop and remove package, retained versions, staged download and installation records | Purge |

Normal restart, stop/start, disable/enable, update, rollback and reinstall preserve endpoint configuration, credentials, profiles and imported history stored through the supported plugin APIs. Package history is separate from plugin data history. Host security audit records remain host-owned records after uninstall. A package rollback cannot reverse a plugin's own destructive data migration; administrators should back up the runtime volume before major upgrades.

Selecting an already installed plugin produces an explicit update/reinstall/replace/cancel choice. Replace is a separately reviewed package identity change; it receives no inherited grants. Duplicate installation never silently succeeds or fails.

## Activation and interrupted transactions

Every acquisition path uses the canonical installer. It validates archive paths and limits, canonical payload SHA-256, publisher signatures, compatibility, dependencies and host route ownership. A prepared runtime transaction cannot execute before PostgreSQL permission decisions commit. The same database transaction writes a durable lifecycle commit receipt.

For an enabled predecessor, activation stops it, atomically publishes the candidate, starts it and checks process health after a startup grace period. Only successful verification commits package history. A failed replacement stops the candidate, withdraws its new grants, restores grants removed by that transaction, restores the prior package and restarts it. An intentionally stopped predecessor remains stopped after a successful switch. Disabled predecessors remain disabled.

Runtime restart never starts a pending transaction. Host startup retries reconciliation while the runtime is coming online: a missing database receipt proves preparation did not commit, while a committed receipt allows activation/health verification or safe rollback. Ambiguous responses therefore do not cause the host to guess whether grants committed. Failures remain visible in diagnostics.

## Manager pages and application pages

Settings → Plugins offers Installed, Updates Available, Available to Install and All. All includes installed plugins plus enabled catalogues, deduplicated by plugin ID. Search and publisher-supplied tag filters apply to these views. Details include identity, description/icon/publisher, installed and available versions, lifecycle/runtime state, permissions and host risk classifications, history, update policy, logs and destructive controls.

The Plugin Manager Settings tab controls lifecycle, permissions, package retention and update policy. A plugin-provided application page contains its actual functionality and configuration, such as Jellyfin endpoint/server/profile settings and sync actions. The detail page links to that application page when the plugin provides one.

## Contribution execution

Contributions execute only while an installation is enabled, compatible and running. Stop/disable prevent backend route execution, event polling, notification-provider delivery and supervised workers. Reserved routes remain owned by the installed package. Navigation, settings contributions, dialogs, overlays, contextual actions, extensions and replacements disappear when execution or the relevant grant is unavailable.

The frontend refreshes observations every five seconds and after local manager operations. Server checks enforce revocation immediately on the next request. Removing privileged native frontend code reloads the browser realm to terminate retained JavaScript.

See [Permissions](plugin-permissions.md), [Updates](plugin-updates.md), [Runtime isolation](plugin-runtime.md), [Storage](plugin-storage.md) and [Management tokens](plugin-management-api.md).
