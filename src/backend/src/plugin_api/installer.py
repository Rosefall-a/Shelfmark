"""Canonical, execution-free planning for plugin installs and updates.

Acquisition is deliberately outside this module. Uploaded files, remote URLs,
and catalogue entries all become a local package path and then pass through the
same inspection, trust, dependency, and permission planning code here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contracts import PluginManifest, version_satisfies
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
        return not self.conflicts and not any(item.state in blocking for item in self.items)


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

    publisher: TrustedPublisher | None = verifier.publishers.get(key_id)
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

    try:
        verified = verifier.inspect(package_path, verify_signature=True)
    except PackageVerificationError:
        return InspectedPackage(
            candidate,
            PackageTrust(
                status=PackageTrustStatus.INVALID_SIGNATURE,
                signature_present=True,
                signature_verified=False,
                publisher_key_id=key_id,
                publisher_identity=publisher.publisher or None,
                warning="The package signature is invalid and installation is blocked.",
            ),
        )

    return InspectedPackage(
        verified,
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
        str(item.get("plugin_id")): item for item in installed if item.get("plugin_id")
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
    return DependencyPlan(tuple(items), tuple(order), tuple(dict.fromkeys(conflicts)))


__all__ = [
    "DependencyPlan",
    "DependencyPlanItem",
    "DependencyState",
    "InspectedPackage",
    "PackageTrust",
    "PackageTrustStatus",
    "inspect_package",
    "plan_dependencies",
]
