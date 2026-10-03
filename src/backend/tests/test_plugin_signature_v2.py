"""Cryptographic verification binds permissions and distinguishes publisher channels."""

import base64
import hashlib
import json
import zipfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from src.plugin_api.installer import inspect_package
from src.plugin_api.updates import (
    PackageVerificationError,
    PluginPackageVerifier,
    TrustedPublisher,
    canonical_payload_digest,
)


def signed_package(tmp_path, *, channel="official", version=2):
    key = Ed25519PrivateKey.generate()
    manifest = {
        "plugin_id": "official.test",
        "name": "Test",
        "version": "0.0.1",
        "entrypoint": "plugin:main",
        "sdk_version_range": "*",
        "application_version_range": "*",
        "capabilities": [],
        "permissions": [],
    }
    payload = {"plugin.py": b"def main(): pass\n"}
    if version == 2:
        payload["package-signature-v2.json"] = json.dumps(
            {"schema_version": 2, "key_id": "test", "manifest": manifest}
        ).encode()
    digest = canonical_payload_digest(list(payload.items()))
    signature = base64.b64encode(key.sign(f"plugin-package-v{version}:{digest}".encode())).decode()
    manifest = {
        **manifest,
        "integrity": {
            "sha256": digest,
            "key_id": "test",
            "signature": ("v2:" if version == 2 else "") + signature,
        },
    }
    path = tmp_path / "test.utp"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, data in payload.items():
            archive.writestr("payload/" + name, data)
    verifier = PluginPackageVerifier(
        {
            "test": TrustedPublisher(
                "test",
                key.public_key().public_bytes_raw(),
                channel=channel,
                plugin_id_prefixes=("official.",),
            )
        }
    )
    return path, verifier


@pytest.mark.parametrize("channel", ["official", "demo", "community"])
def test_verified_channel_is_registry_owned(tmp_path, channel):
    path, verifier = signed_package(tmp_path, channel=channel)
    package = inspect_package(path, verifier)
    assert package.trust.signature_verified
    assert package.trust.publisher_channel == channel


def test_legacy_valid_signature_does_not_establish_official_status(tmp_path):
    path, verifier = signed_package(tmp_path, version=1)
    assert inspect_package(path, verifier).trust.publisher_channel == "community"


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "0.0.2"),
        ("plugin_id", "official.other"),
        (
            "permissions",
            [{"capability": {"name": "frontend.native", "version": 1}, "rationale": "Escalate"}],
        ),
    ],
)
def test_manifest_tampering_rejected_before_signature_or_consent(tmp_path, field, value):
    path, verifier = signed_package(tmp_path)
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(entries["manifest.json"])
    manifest[field] = value
    if field == "permissions":
        manifest["capabilities"] = [{"name": "frontend.native", "version": 1}]
    entries["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    with pytest.raises(PackageVerificationError, match="envelope"):
        inspect_package(path, verifier)


def test_unknown_signature_never_claims_official(tmp_path):
    path, _ = signed_package(tmp_path)
    inspected = inspect_package(path, PluginPackageVerifier({}))
    assert inspected.trust.status == "unknown_publisher"
    assert inspected.trust.publisher_channel == "unverified"


def test_invalid_signature_is_blocked(tmp_path):
    path, verifier = signed_package(tmp_path)
    verifier.publishers["test"] = TrustedPublisher(
        "test", Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    )
    inspected = inspect_package(path, verifier)
    assert inspected.trust.status == "invalid_signature"
    assert not inspected.trust.installable


def test_legacy_registry_pins_prevent_manifest_substitution(tmp_path):
    path, verifier = signed_package(tmp_path, version=1, channel="demo")
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(entries["manifest.json"])
    digest = manifest["integrity"]["sha256"]
    claim = {key: value for key, value in manifest.items() if key != "integrity"}
    pin = hashlib.sha256(
        json.dumps(claim, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    original = verifier.publishers["test"]
    verifier.publishers["test"] = TrustedPublisher(
        "test",
        original.public_key,
        channel="demo",
        require_manifest_binding=True,
        legacy_manifest_hashes={digest: [pin]},
    )
    assert inspect_package(path, verifier).trust.publisher_channel == "demo"
    manifest["version"] = "0.0.9"
    entries["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    with pytest.raises(PackageVerificationError, match="legacy signed manifest"):
        inspect_package(path, verifier)


def test_unreviewed_legacy_signature_cannot_enter_a_registered_identity(tmp_path):
    path, verifier = signed_package(tmp_path, version=1)
    original = verifier.publishers["test"]
    verifier.publishers["test"] = TrustedPublisher(
        "test", original.public_key, require_manifest_binding=True
    )
    with pytest.raises(PackageVerificationError, match="use a v2"):
        inspect_package(path, verifier)
