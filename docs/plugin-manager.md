# Plugin Manager

The implemented lifecycle is documented in the repository wiki:

- [Lifecycle and data preservation](../wiki/docs/development/plugin-lifecycle.md)
- [Updates, automatic policy and rollback](../wiki/docs/development/plugin-updates.md)
- [Permissions and host-owned risk registry](../wiki/docs/development/plugin-permissions.md)
- [Runtime and Bubblewrap capability reporting](../wiki/docs/development/plugin-runtime.md)
- [Plugin storage and secrets](../wiki/docs/development/plugin-storage.md)
- [Remote management tokens and scopes](../wiki/docs/development/plugin-management-api.md)
- [Plugin application pages and UI contract](../wiki/docs/development/plugin-ui.md)
- [Validation with external plugin packages](../wiki/docs/development/plugin-validation.md)

The backend owns installation identity, metadata, staged releases and update policy;
PostgreSQL owns grants and lifecycle commit receipts. The isolated runtime owns
packages, process state and persistent plugin data. All acquisition paths use the
same verifier, permission consent and activation service. No plugin code is
imported into the core backend.

Package replacement is separate from data deletion. Normal lifecycle operations
preserve configuration, secrets, profiles and imported history. Only uninstall or
explicitly confirmed purge removes plugin-owned state. Startup verification checks
process liveness after a grace period; it cannot prove semantic correctness or
reverse plugin-owned data migrations. See the linked implementation documentation
for operational limits and backup requirements.
