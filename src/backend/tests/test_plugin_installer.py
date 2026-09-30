"""Regression coverage for the canonical plugin installer planner."""

from __future__ import annotations

import base64
import hashlib
import json
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.plugin_api.contracts import PluginManifest
from src.plugin_api.installer import (
    DependencyState,
    PackageTrustStatus,
    inspect_package,
    plan_dependencies,
)
from src.plugin_api.updates import PluginPackageVerifier, TrustedPublisher


def _digest(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()


def _manifest(
    *,
    digest: str,
    signature: str | None = None,
    key_id: str | None = None,
    dependencies: list[dict] | None = None,
) -> dict:
    return {
        "manifest_version": 1,
        "plugin_id": "example.candidate",
        "name": "Candidate",
        "version": "2.0.0",
        "entrypoint": "plugin:main",
        "sdk_version_range": "*",
        "application_version_range": "*",
        "capabilities": [],
        "permissions": [],
        "dependencies": dependencies or [],
        "integrity": {"sha256": digest, "signature": signature, "key_id": key_id},
    }


def _package(path: Path, manifest: dict, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, data in files.items():
            archive.writestr(f"payload/{name}", data)


def test_signature_states_are_not_collapsed_into_untrusted(tmp_path: Path) -> None:
    files = {"plugin.py": b"safe"}
    digest = _digest(files)
    package = tmp_path / "plugin.download"

    _package(package, _manifest(digest=digest), files)
    unsigned = inspect_package(package, PluginPackageVerifier(require_signature=False))
    assert unsigned.trust.status is PackageTrustStatus.UNSIGNED
    assert unsigned.trust.installable is True

    key = Ed25519PrivateKey.generate()
    signature = base64.b64encode(key.sign(b"plugin-package-v1:" + digest.encode("ascii"))).decode(
        "ascii"
    )
    _package(package, _manifest(digest=digest, signature=signature, key_id="unknown"), files)
    unknown = inspect_package(package, PluginPackageVerifier(require_signature=False))
    assert unknown.trust.status is PackageTrustStatus.UNKNOWN_PUBLISHER
    assert unknown.trust.signature_present is True
    assert unknown.trust.signature_verified is False

    trusted = TrustedPublisher("known", key.public_key().public_bytes_raw(), "Example Publisher")
    bad_signature = base64.b64encode(b"x" * 64).decode("ascii")
    _package(package, _manifest(digest=digest, signature=bad_signature, key_id="known"), files)
    invalid = inspect_package(
        package,
        PluginPackageVerifier({"known": trusted}, require_signature=False),
    )
    assert invalid.trust.status is PackageTrustStatus.INVALID_SIGNATURE
    assert invalid.trust.installable is False

    _package(package, _manifest(digest=digest, signature=signature, key_id="known"), files)
    verified = inspect_package(
        package,
        PluginPackageVerifier({"known": trusted}, require_signature=False),
    )
    assert verified.trust.status is PackageTrustStatus.TRUSTED
    assert verified.trust.publisher_identity == "Example Publisher"


def test_dependency_plan_reports_missing_conflicts_available_and_cycles() -> None:
    manifest = PluginManifest.model_validate(
        _manifest(
            digest="0" * 64,
            dependencies=[
                {"plugin_id": "required.missing", "version_range": "^1.0.0"},
                {"plugin_id": "required.conflict", "version_range": ">=2.0.0"},
                {"plugin_id": "optional.missing", "version_range": "*", "optional": True},
                {"plugin_id": "available.plugin", "version_range": "^1.0.0"},
            ],
        )
    )
    plan = plan_dependencies(
        manifest,
        (
            {
                "plugin_id": "required.conflict",
                "version": "1.0.0",
                "dependencies": [
                    {
                        "plugin_id": "example.candidate",
                        "version_range": "*",
                        "optional": False,
                    }
                ],
            },
        ),
        (
            {
                "plugin_id": "available.plugin",
                "version": "1.3.0",
                "url": "https://example.com/available.utp",
                "dependencies": [
                    {
                        "plugin_id": "example.candidate",
                        "version_range": "*",
                        "optional": False,
                    }
                ],
            },
        ),
    )
    states = {item.plugin_id: item.state for item in plan.items}
    assert states == {
        "required.missing": DependencyState.MISSING,
        "required.conflict": DependencyState.INCOMPATIBLE,
        "optional.missing": DependencyState.OPTIONAL_MISSING,
        "available.plugin": DependencyState.AVAILABLE,
    }
    assert plan.ready is False
    assert any("cycle" in conflict for conflict in plan.conflicts)
