"""Canonical security policy and lifecycle for plugin installs and updates.

Acquisition is deliberately outside this module. Uploaded files, remote URLs,
and catalogue entries all become a local package path and then pass through the
same inspection, trust, dependency, permission consent, commit and activation
code here. Runtime execution stays behind the isolated runtime boundary.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import quote
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidSignature
from sqlalchemy import select, update
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.plugin_permission_audit import PluginPermissionAudit
from src.database.models.plugin_permissions import PluginPermissionGrant, PluginPermissionRequest

from .backend_routes import BackendRouteConflictError, validate_host_route_ownership
from .capabilities import (
    PermissionDelta,
    calculate_permission_delta,
    capability_definition,
    package_identity_can_retain_grants,
)
from .contracts import (
    BackendRouteScope,
    CapabilityRef,
    PluginManifest,
    PluginPackageIdentity,
    parse_semver,
    version_satisfies,
)
from .runtime_client import PluginRuntimeClient, PluginRuntimeRequestError, PluginRuntimeUnavailable
from .updates import (
    PackageVerificationError,
    PluginPackageVerifier,
    TrustedPublisher,
    VerifiedPackage,
)


class PackageTrustStatus(StrEnum):
    """Package-signature state, intentionally separate from source provenance."""

    TRUSTED = "trusted"
    UNKNOWN_PUBLISHER = "unknown_publisher"
    INVALID_SIGNATURE = "invalid_signature"
    UNSIGNED = "unsigned"


@dataclass(frozen=True, slots=True)
class PackageTrust:
    status: PackageTrustStatus
    signature_present: bool
    signature_verified: bool
    publisher_key_id: str | None
    publisher_identity: str | None
    warning: str | None

    @property
    def installable(self) -> bool:
        """Invalid signatures are never an administrator-overridable warning."""
        return self.status is not PackageTrustStatus.INVALID_SIGNATURE

    @property
    def is_verified(self) -> bool:
        return self.status is PackageTrustStatus.TRUSTED


@dataclass(frozen=True, slots=True)
class InspectedPackage:
    package: VerifiedPackage
    trust: PackageTrust


class DependencyState(StrEnum):
    SATISFIED = "satisfied"
    MISSING = "missing"
    INCOMPATIBLE = "incompatible"
    OPTIONAL_MISSING = "optional_missing"
    OPTIONAL_INCOMPATIBLE = "optional_incompatible"
    AVAILABLE = "available"


@dataclass(frozen=True, slots=True)
class DependencyPlanItem:
    plugin_id: str
    version_range: str
    optional: bool
    state: DependencyState
    installed_version: str | None = None
    available_version: str | None = None
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class DependencyPlan:
    items: tuple[DependencyPlanItem, ...]
    installation_order: tuple[str, ...]
    conflicts: tuple[str, ...]

    @property
    def ready(self) -> bool:
        blocking = {
            DependencyState.MISSING,
            DependencyState.INCOMPATIBLE,
            DependencyState.AVAILABLE,
        }
        return not self.conflicts and not any(
            item.state in blocking and not item.optional for item in self.items
        )


def inspect_package(
    package_path: Path,
    verifier: PluginPackageVerifier,
) -> InspectedPackage:
    """Validate package bytes first, then classify signature trust precisely."""
    candidate = verifier.inspect(package_path, verify_signature=False)
    integrity = candidate.manifest.integrity
    signature_present = integrity.signature is not None
    key_id = integrity.key_id

    if not signature_present:
        return InspectedPackage(
            candidate,
            PackageTrust(
                status=PackageTrustStatus.UNSIGNED,
                signature_present=False,
                signature_verified=False,
                publisher_key_id=key_id,
                publisher_identity=None,
                warning="The package is unsigned. Its publisher identity cannot be verified.",
            ),
        )

    if not key_id:
        return InspectedPackage(
            candidate,
            PackageTrust(
                status=PackageTrustStatus.INVALID_SIGNATURE,
                signature_present=True,
                signature_verified=False,
                publisher_key_id=None,
                publisher_identity=None,
                warning="The signed package does not identify a publisher key.",
            ),
        )

    # A signature's encoding/length is verifiable even without a publisher key.
    try:
        assert integrity.signature is not None
        signature_bytes = base64.b64decode(integrity.signature, validate=True)
        if len(signature_bytes) != 64:
            raise ValueError("invalid Ed25519 signature length")
        publisher: TrustedPublisher | None = verifier.publishers.get(key_id)
        if publisher is not None:
            publisher.verifier().verify(
                signature_bytes, verifier.SIGNING_PREFIX + candidate.payload_digest.encode("ascii")
            )
    except (ValueError, binascii.Error, InvalidSignature, PackageVerificationError):
        return InspectedPackage(
            candidate,
            PackageTrust(
                status=PackageTrustStatus.INVALID_SIGNATURE,
                signature_present=True,
                signature_verified=False,
                publisher_key_id=key_id,
                publisher_identity=None,
                warning="The package signature is invalid and installation is blocked.",
            ),
        )

    if publisher is None or not publisher.allows_plugin(candidate.manifest.plugin_id):
        return InspectedPackage(
            candidate,
            PackageTrust(
                status=PackageTrustStatus.UNKNOWN_PUBLISHER,
                signature_present=True,
                signature_verified=False,
                publisher_key_id=key_id,
                publisher_identity=publisher.publisher if publisher else None,
                warning=(
                    "The package is signed, but the publisher key is not trusted for this plugin."
                ),
            ),
        )

    return InspectedPackage(
        candidate,
        PackageTrust(
            status=PackageTrustStatus.TRUSTED,
            signature_present=True,
            signature_verified=True,
            publisher_key_id=key_id,
            publisher_identity=publisher.publisher or None,
            warning=None,
        ),
    )


def _summary_version(summary: Mapping[str, Any] | None) -> str | None:
    if summary is None:
        return None
    value = summary.get("version")
    return str(value) if isinstance(value, str) else None


def _dependencies(summary: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    value = summary.get("dependencies", ())
    if not isinstance(value, (list, tuple)):
        return ()
    return (item for item in value if isinstance(item, Mapping))


def plan_dependencies(
    manifest: PluginManifest,
    installed: Iterable[Mapping[str, Any]],
    available: Iterable[Mapping[str, Any]] = (),
) -> DependencyPlan:
    """Resolve one candidate against installed and source-advertised versions."""
    installed_by_id = {
        str(item.get("plugin_id")): item
        for item in installed
        if item.get("plugin_id") and not item.get("installation_pending")
    }
    available_by_id = {
        str(item.get("plugin_id")): item for item in available if item.get("plugin_id")
    }
    items: list[DependencyPlanItem] = []
    conflicts: list[str] = []

    for dependency in manifest.dependencies:
        installed_item = installed_by_id.get(dependency.plugin_id)
        installed_version = _summary_version(installed_item)
        available_item = available_by_id.get(dependency.plugin_id)
        available_version = _summary_version(available_item)
        source_url = (
            str(available_item.get("url"))
            if available_item is not None and isinstance(available_item.get("url"), str)
            else None
        )
        if installed_version and version_satisfies(installed_version, dependency.version_range):
            state = DependencyState.SATISFIED
        elif installed_version:
            state = (
                DependencyState.OPTIONAL_INCOMPATIBLE
                if dependency.optional
                else DependencyState.INCOMPATIBLE
            )
        elif available_version and version_satisfies(available_version, dependency.version_range):
            state = DependencyState.AVAILABLE
        else:
            state = (
                DependencyState.OPTIONAL_MISSING if dependency.optional else DependencyState.MISSING
            )
        if state is DependencyState.INCOMPATIBLE:
            conflicts.append(
                f"{dependency.plugin_id} {installed_version} does not satisfy "
                f"{dependency.version_range}"
            )
        items.append(
            DependencyPlanItem(
                plugin_id=dependency.plugin_id,
                version_range=dependency.version_range,
                optional=dependency.optional,
                state=state,
                installed_version=installed_version,
                available_version=available_version,
                source_url=source_url,
            )
        )

    graph: dict[str, tuple[str, ...]] = {
        plugin_id: tuple(
            str(item.get("plugin_id"))
            for item in _dependencies(summary)
            if not bool(item.get("optional")) and item.get("plugin_id")
        )
        for plugin_id, summary in available_by_id.items()
    }
    graph.update(
        {
            plugin_id: tuple(
                str(item.get("plugin_id"))
                for item in _dependencies(summary)
                if not bool(item.get("optional")) and item.get("plugin_id")
            )
            for plugin_id, summary in installed_by_id.items()
        }
    )
    graph[manifest.plugin_id] = tuple(
        dependency.plugin_id for dependency in manifest.dependencies if not dependency.optional
    )
    visiting: set[str] = set()
    visited: set[str] = set()
    order: list[str] = []

    def visit(plugin_id: str, path: tuple[str, ...]) -> None:
        if plugin_id in visiting:
            cycle = " -> ".join((*path, plugin_id))
            conflicts.append(f"dependency cycle detected: {cycle}")
            return
        if plugin_id in visited:
            return
        visiting.add(plugin_id)
        for dependency_id in graph.get(plugin_id, ()):
            if dependency_id in graph:
                visit(dependency_id, (*path, plugin_id))
        visiting.remove(plugin_id)
        visited.add(plugin_id)
        order.append(plugin_id)

    visit(manifest.plugin_id, ())
    # Check transitive dependencies and reverse constraints on an update, not
    # just the candidate's direct declarations. Available packages are preview
    # hints; they cannot satisfy the installed graph before activation.
    versions = {plugin_id: _summary_version(item) for plugin_id, item in installed_by_id.items()}
    versions[manifest.plugin_id] = manifest.version
    for owner_id, summary in installed_by_id.items():
        if owner_id == manifest.plugin_id:
            continue
        for summary_dependency in _dependencies(summary):
            dependency_id = str(summary_dependency.get("plugin_id", ""))
            if bool(summary_dependency.get("optional")):
                continue
            if owner_id not in visited and dependency_id != manifest.plugin_id:
                continue
            version = versions.get(dependency_id)
            version_range = str(summary_dependency.get("version_range", "*"))
            if version is None or not version_satisfies(version, version_range):
                conflicts.append(f"{owner_id} requires {dependency_id} matching {version_range}")
    return DependencyPlan(tuple(items), tuple(order), tuple(dict.fromkeys(conflicts)))


class InstallationError(ValueError):
    """An installation policy rejection, translated to HTTP only by the routes."""

    def __init__(self, status_code: int, detail: str | dict[str, Any]) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail
        self.plan: InstallationPlan | None = None
        self.inspected: InspectedPackage | None = None


@dataclass(frozen=True, slots=True)
class InstallationConsent:
    """Explicit administrator decisions; source provenance never grants trust."""

    allow_untrusted: bool = False
    approved_permissions: tuple[str, ...] = ()
    admin_password: str | None = None
    confirm_dangerous: bool = False
    expected_digest: str | None = None


@dataclass(frozen=True, slots=True)
class InstallationPlan:
    inspected: InspectedPackage
    installation_id: UUID
    dependencies: DependencyPlan
    permissions: PermissionDelta
    installed: dict[str, Any] | None = None
    can_retain_grants: bool = False


def permission_key(capability: CapabilityRef) -> str:
    """Stable consent key shared by installs and updates."""
    return f"{capability.name.value}:v{capability.version}"


class PluginInstaller:
    """Own the security-sensitive lifecycle for every acquisition source.

    Acquisition supplies bounded bytes. Inspection uses a private snapshot and
    the exact same bytes are sent to the runtime after consent. The runtime owns
    safe extraction and atomic package replacement; this service owns trust and
    grants and commits them before activation. Dependencies never supply grants.
    """

    def __init__(
        self,
        runtime: PluginRuntimeClient,
        verifier: PluginPackageVerifier,
        password_verifier: Callable[[str, str], bool],
    ) -> None:
        self.runtime = runtime
        self.verifier = verifier
        self.password_verifier = password_verifier

    def _inspect_snapshot(self, package: bytes) -> InspectedPackage:
        with tempfile.TemporaryDirectory(prefix="plugin-candidate-") as directory:
            snapshot = Path(directory) / "package.utp"
            snapshot.write_bytes(package)
            return inspect_package(snapshot, self.verifier)

    async def plan_update(
        self, plugin_id: str, inspected: InspectedPackage, db: AsyncSession
    ) -> InstallationPlan:
        """Compare only this installation's identity, declarations and grants."""
        manifest = inspected.package.manifest
        if manifest.plugin_id != plugin_id:
            raise InstallationError(
                400, "Updated package plugin ID does not match the installed plugin."
            )
        installed_plugins = await self.runtime.plugins()
        installed = next(
            (item for item in installed_plugins if item.get("plugin_id") == plugin_id), None
        )
        if installed is None or not installed.get("installation_id"):
            raise InstallationError(409, "Plugin installation identity is missing.")
        if parse_semver(manifest.version) <= parse_semver(str(installed.get("version", "0.0.0"))):
            raise InstallationError(409, "Plugin update version must be newer.")
        installation_id = UUID(str(installed["installation_id"]))
        installed_trust = installed.get("trust")
        installed_trust = installed_trust if isinstance(installed_trust, dict) else {}
        previous_identity = PluginPackageIdentity(
            plugin_id=plugin_id,
            publisher_key_id=installed_trust.get("publisher_key_id") or installed.get("publisher"),
        )
        candidate_identity = PluginPackageIdentity(
            plugin_id=manifest.plugin_id,
            publisher_key_id=inspected.trust.publisher_key_id,
        )
        can_retain = (
            installed_trust.get("status") == PackageTrustStatus.TRUSTED.value
            and inspected.trust.is_verified
            and package_identity_can_retain_grants(previous_identity, candidate_identity)
        )
        if installed_trust.get("status") == PackageTrustStatus.TRUSTED.value and not can_retain:
            raise InstallationError(
                409,
                "The verified update publisher does not match the installed package. "
                "Install it as a new lifecycle instance and review permissions again.",
            )
        grant_rows = (
            await db.execute(
                select(
                    PluginPermissionGrant.capability, PluginPermissionGrant.capability_version
                ).where(
                    PluginPermissionGrant.plugin_id == plugin_id,
                    PluginPermissionGrant.installation_id == installation_id,
                    PluginPermissionGrant.revoked_at.is_(None),
                )
            )
        ).all()
        grants = tuple(CapabilityRef(name=name, version=version) for name, version in grant_rows)
        previous = (
            tuple(CapabilityRef.model_validate(ref) for ref in installed.get("permission_refs", []))
            if can_retain
            else ()
        )
        delta = calculate_permission_delta(
            previous,
            tuple(permission.capability for permission in manifest.permissions),
            grants if can_retain else (),
        )
        dependencies = plan_dependencies(
            manifest, (item for item in installed_plugins if item.get("plugin_id") != plugin_id)
        )
        return InstallationPlan(
            inspected, installation_id, dependencies, delta, installed, can_retain
        )

    def confirm(
        self, plan: InstallationPlan, consent: InstallationConsent, admin: Any
    ) -> list[str]:
        """One consent and reauthentication rule for installs and permission increases."""
        trust = plan.inspected.trust
        if not trust.installable:
            raise InstallationError(400, {"code": "invalid_signature", "message": trust.warning})
        if not trust.is_verified and not consent.allow_untrusted:
            raise InstallationError(
                409,
                {"code": "untrusted_plugin", "message": "Explicit unverified consent is required."},
            )
        if not plan.dependencies.ready:
            raise InstallationError(
                409,
                {
                    "code": "dependency_resolution_failed",
                    "message": "Required plugin dependencies must be installed compatibly first.",
                },
            )
        new_keys = {permission_key(ref) for ref in plan.permissions.newly_requested_grants}
        approved = set(consent.approved_permissions)
        if not approved.issubset(new_keys):
            raise InstallationError(400, "Consent contains an undeclared or unchanged permission.")
        dangerous = [
            permission_key(ref)
            for ref in plan.permissions.newly_requested_grants
            if permission_key(ref) in approved
            and capability_definition(ref.name).highly_privileged
            and not trust.is_verified
        ]
        if dangerous:
            if not consent.confirm_dangerous:
                raise InstallationError(
                    409,
                    {
                        "code": "dangerous_permissions_confirmation_required",
                        "message": "Explicit confirmation is required for dangerous unverified permissions.",
                        "permissions": dangerous,
                    },
                )
            if not consent.admin_password or not self.password_verifier(
                consent.admin_password, getattr(admin, "password_hash", "")
            ):
                raise InstallationError(
                    401,
                    {
                        "code": "administrator_reauthentication_failed",
                        "message": "Administrator password re-entry is required for these permissions.",
                        "permissions": dangerous,
                    },
                )
        return dangerous

    async def install(
        self,
        package: bytes,
        *,
        consent: InstallationConsent,
        admin: Any,
        db: AsyncSession,
        source: dict[str, Any] | None = None,
        update_plugin_id: str | None = None,
    ) -> dict[str, Any]:
        """Validate, resolve, authorize, atomically install, then activate and check health."""
        if len(package) > self.verifier.max_package_bytes:
            raise InstallationError(413, "Plugin package exceeds the 64 MiB upload limit.")
        inspected = await asyncio.to_thread(self._inspect_snapshot, package)
        manifest = inspected.package.manifest
        if not inspected.trust.installable:
            error = InstallationError(
                400, {"code": "invalid_signature", "message": inspected.trust.warning}
            )
            error.inspected = inspected
            raise error
        if (
            consent.expected_digest
            and inspected.package.payload_digest.lower() != consent.expected_digest.lower()
        ):
            raise InstallationError(
                409, "The remote plugin changed after preview; review it again before installing."
            )
        if update_plugin_id is not None:
            plan = await self.plan_update(update_plugin_id, inspected, db)
        else:
            installed = await self.runtime.plugins() if manifest.dependencies else ()
            plan = InstallationPlan(
                inspected,
                uuid4(),
                plan_dependencies(manifest, installed),
                calculate_permission_delta(
                    (), tuple(permission.capability for permission in manifest.permissions), ()
                ),
            )
        if any(route.scope is BackendRouteScope.HOST for route in manifest.backend_routes):
            try:
                validate_host_route_ownership(
                    await self.runtime.plugins(),
                    candidate_plugin_id=manifest.plugin_id,
                    candidate_routes=manifest.backend_routes,
                )
            except BackendRouteConflictError as exc:
                raise InstallationError(
                    409, {"code": "plugin_route_conflict", "message": str(exc)}
                ) from exc
        try:
            dangerous = self.confirm(plan, consent, admin)
        except InstallationError as exc:
            exc.plan = plan
            raise
        return await self._commit(plan, package, consent, admin, db, source, dangerous)

    async def _commit(
        self,
        plan: InstallationPlan,
        package: bytes,
        consent: InstallationConsent,
        admin: Any,
        db: AsyncSession,
        source: dict[str, Any] | None,
        dangerous: list[str],
    ) -> dict[str, Any]:
        manifest = plan.inspected.package.manifest
        trust = plan.inspected.trust
        plugin_id = manifest.plugin_id
        now = int(time.time())
        approved = set(consent.approved_permissions)
        replacing = plan.installed is not None
        operation_id = str(uuid4())
        prepared = False
        commit_attempted = False
        try:
            if replacing and not plan.can_retain_grants:
                await db.execute(
                    update(PluginPermissionGrant)
                    .where(
                        PluginPermissionGrant.plugin_id == plugin_id,
                        PluginPermissionGrant.installation_id == plan.installation_id,
                        PluginPermissionGrant.revoked_at.is_(None),
                    )
                    .values(revoked_at=now)
                )
            rows: list[Any] = []
            for ref in plan.permissions.newly_requested_grants:
                allowed = permission_key(ref) in approved
                rationale = next(p.rationale for p in manifest.permissions if p.capability == ref)
                identity = {
                    "plugin_id": plugin_id,
                    "installation_id": plan.installation_id,
                    "capability": ref.name.value,
                    "capability_version": ref.version,
                }
                rows.append(
                    PluginPermissionRequest(
                        **identity,
                        rationale=rationale,
                        status="approved" if allowed else "denied",
                        resolved_at=now,
                        resolved_by=getattr(admin, "id", None),
                    )
                )
                if allowed:
                    rows.append(PluginPermissionGrant(**identity))
                rows.append(
                    PluginPermissionAudit(
                        **identity,
                        user_id=getattr(admin, "id", None),
                        decision="allowed" if allowed else "denied",
                        reason="administrator update consent"
                        if replacing
                        else "administrator install consent",
                    )
                )
            db.add_all(rows)
            options: dict[str, Any] = {
                "installation_id": str(plan.installation_id),
                "operation_id": operation_id,
                "source_metadata": source,
                "trust_metadata": {
                    "status": trust.status.value,
                    "signature_present": trust.signature_present,
                    "signature_verified": trust.signature_verified,
                    "publisher_key_id": trust.publisher_key_id,
                    "publisher_identity": trust.publisher_identity,
                },
            }
            if replacing:
                options["replace"] = True
                assert plan.installed is not None
                options["expected_version"] = str(plan.installed["version"])
            result = await self.runtime.install_package(
                package, f"{plugin_id}-{manifest.version}.utp", **options
            )
            if result.get("operation_id") != operation_id:
                raise PluginRuntimeRequestError(
                    "runtime did not prepare the installation transaction"
                )
            prepared = True
            if plan.can_retain_grants:
                removed = {(ref.name.value, ref.version) for ref in plan.permissions.removed}
                for grant in await db.scalars(
                    select(PluginPermissionGrant).where(
                        PluginPermissionGrant.plugin_id == plugin_id,
                        PluginPermissionGrant.installation_id == plan.installation_id,
                        PluginPermissionGrant.revoked_at.is_(None),
                    )
                ):
                    if (grant.capability, grant.capability_version) in removed:
                        grant.revoked_at = now
            commit_attempted = True
            await db.commit()
        except Exception as exc:
            await db.rollback()
            # A lost COMMIT acknowledgement is not proof of rollback. Restoring
            # old unverified code could expose it to a newly committed grant.
            # Only abort on a definite rejection or an error before COMMIT.
            definite_rejection = not commit_attempted or isinstance(
                exc, (DataError, IntegrityError)
            )
            if prepared and definite_rejection:
                try:
                    await self.runtime.finish_installation(plugin_id, operation_id, commit=False)
                except (PluginRuntimeRequestError, PluginRuntimeUnavailable):
                    logging.getLogger(__name__).exception(
                        "Plugin installation remains pending and cannot activate: plugin_id=%s",
                        plugin_id,
                    )
            raise

        # A failed finalization leaves the package durably disabled and pending.
        # Never fall back to start or claim activation on an ambiguous commit.
        await self.runtime.finish_installation(plugin_id, operation_id, commit=True)

        status = result.get("status", "updated" if replacing else "installed")
        healthy = False
        if plan.installed is None or plan.installed.get("enabled"):
            try:
                encoded = quote(plugin_id, safe="")
                if manifest.dependencies:
                    dependencies = plan_dependencies(manifest, await self.runtime.plugins())
                    if not dependencies.ready:
                        raise PluginRuntimeRequestError(
                            "plugin dependencies changed before activation"
                        )
                await self.runtime.start(encoded, user_id=str(getattr(admin, "id", "")) or None)
                healthy = await self.runtime.plugin_health(encoded)
                status = "running" if healthy else "unhealthy"
            except (PluginRuntimeRequestError, PluginRuntimeUnavailable) as exc:
                logging.getLogger(__name__).warning(
                    "Plugin activation failed: plugin_id=%s error=%s", plugin_id, exc
                )
                status = "failed_activation"
        response = {
            "plugin_id": plugin_id,
            "version": manifest.version,
            "permissions_requested": len(plan.permissions.newly_requested_grants),
            "permissions_granted": len(approved),
            "dangerous_permissions_reauthenticated": dangerous,
            "trust_status": trust.status.value,
            "install_status": result.get("status", "updated" if replacing else "installed"),
            "status": status,
            "healthy": healthy,
        }
        if replacing:
            response["permission_delta"] = plan.permissions.model_dump(mode="json")
        else:
            response.update(
                {
                    "name": manifest.name,
                    "publisher": trust.publisher_identity,
                    "publisher_key_id": trust.publisher_key_id,
                    "installation_id": str(plan.installation_id),
                    "permissions_denied": len(plan.permissions.newly_requested_grants)
                    - len(approved),
                    "trust_warning": trust.warning,
                }
            )
        return response


__all__ = [
    "DependencyPlan",
    "DependencyPlanItem",
    "DependencyState",
    "InspectedPackage",
    "InstallationConsent",
    "InstallationError",
    "InstallationPlan",
    "PluginInstaller",
    "PackageTrust",
    "PackageTrustStatus",
    "inspect_package",
    "plan_dependencies",
]
