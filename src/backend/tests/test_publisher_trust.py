from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import zipfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.plugin_api.publisher_trust import PublisherTrustError, load_trusted_publishers
from src.plugin_api.updates import PackageVerificationError, PluginPackageVerifier


def registry_entry(private_key: Ed25519PrivateKey, **overrides: object) -> dict[str, object]:
    public_key = private_key.public_key().public_bytes_raw()
    entry: dict[str, object] = {
        "key_id": "official-test",
        "publisher": "Test Publisher",
        "public_key_b64": base64.b64encode(public_key).decode("ascii"),
        "public_key_sha256": hashlib.sha256(public_key).hexdigest(),
        "status": "active",
        "plugin_id_prefixes": ["example."],
    }
    entry.update(overrides)
    return entry


def write_registry(path: Path, *entries: dict[str, object]) -> None:
    path.write_text(json.dumps({"schema_version": 1, "publishers": list(entries)}))


def write_signed_package(path: Path, private_key: Ed25519PrivateKey, plugin_id: str) -> None:
    files = {"plugin.py": b"def main():\n    return None\n"}
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    payload_digest = digest.hexdigest()
    manifest = {
        "manifest_version": 1,
        "plugin_id": plugin_id,
        "name": "Trust Test",
        "version": "1.0.0",
        "entrypoint": "plugin:main",
        "sdk_version_range": "*",
        "application_version_range": "*",
        "integrity": {
            "sha256": payload_digest,
            "key_id": "official-test",
            "signature": base64.b64encode(
                private_key.sign(b"plugin-package-v1:" + payload_digest.encode("ascii"))
            ).decode("ascii"),
        },
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, content in files.items():
            archive.writestr(f"payload/{name}", content)


def test_registry_rejects_duplicate_key_and_key_digest_mismatch(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    registry = tmp_path / "publishers.json"
    entry = registry_entry(private_key)
    write_registry(registry, entry, entry)
    with pytest.raises(PublisherTrustError, match="duplicate"):
        load_trusted_publishers(registry)

    write_registry(registry, registry_entry(private_key, public_key_sha256="0" * 64))
    with pytest.raises(PublisherTrustError, match="digest"):
        load_trusted_publishers(registry)


def test_registry_enforces_publisher_status_and_plugin_scope(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    registry = tmp_path / "publishers.json"
    write_registry(registry, registry_entry(private_key, status="retiring"))
    publisher = load_trusted_publishers(registry)["official-test"]
    assert publisher.allows_plugin("example.plugin")
    assert not publisher.allows_plugin("other.plugin")

    write_registry(registry, registry_entry(private_key, status="revoked"))
    assert not load_trusted_publishers(registry)["official-test"].allows_plugin("example.plugin")


def test_verifier_rejects_revoked_or_out_of_scope_signers(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    registry = tmp_path / "publishers.json"
    package = tmp_path / "plugin.utp"
    write_signed_package(package, private_key, "example.plugin")
    write_registry(registry, registry_entry(private_key, status="revoked"))
    verifier = PluginPackageVerifier(load_trusted_publishers(registry))
    with pytest.raises(PackageVerificationError, match="trusted for this plugin"):
        verifier.inspect(package)

    write_registry(registry, registry_entry(private_key))
    write_signed_package(package, private_key, "other.plugin")
    with pytest.raises(PackageVerificationError, match="trusted for this plugin"):
        PluginPackageVerifier(load_trusted_publishers(registry)).inspect(package)


def test_production_identities_keep_official_demo_and_generic_trust_separate() -> None:
    publishers = load_trusted_publishers()
    official = publishers["unnamed-tracking-official-2026-10-v1"]
    examples = publishers["unnamed-tracking-examples-2026-10-v1"]
    generic = publishers["unnamed-tracking-generic-2026-10-v1"]
    assert len({official.public_key, examples.public_key, generic.public_key}) == 3
    assert official.channel == "official" and official.allows_plugin("official.pwa")
    assert not official.allows_plugin("example.lifecycle")
    assert examples.channel == "demo" and examples.allows_plugin("example.lifecycle")
    assert generic.channel == "community" and generic.allows_plugin("example.lifecycle")
    assert generic.allows_plugin("plugin.lifecycle")
    assert not examples.allows_plugin("official.pwa")
    assert not generic.allows_plugin("official.pwa")
    assert publishers["official-example-2026"].channel == "demo"
