"""Load the reviewed publisher trust policy used for plugin verification."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path
import re

from .updates import TrustedPublisher


class PublisherTrustError(ValueError):
    """Raised when the deployed publisher trust policy is malformed."""


_KEY_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_STATUSES = {"active", "retiring", "revoked"}
_DEFAULT_REGISTRY = Path(__file__).with_name("trusted_publishers.json")


def load_trusted_publishers(path: Path | None = None) -> dict[str, TrustedPublisher]:
    """Load a reviewed registry; revoked keys remain visible but are never trusted."""
    registry_path = path or _DEFAULT_REGISTRY
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublisherTrustError("publisher trust registry cannot be read") from exc
    if data.get("schema_version") != 1 or not isinstance(data.get("publishers"), list):
        raise PublisherTrustError("publisher trust registry has an unsupported schema")

    publishers: dict[str, TrustedPublisher] = {}
    for entry in data["publishers"]:
        if not isinstance(entry, dict):
            raise PublisherTrustError("publisher trust registry contains an invalid entry")
        key_id = entry.get("key_id")
        status = entry.get("status")
        encoded_key = entry.get("public_key_b64")
        scopes = entry.get("plugin_id_prefixes")
        digest = entry.get("public_key_sha256")
        if (
            not isinstance(key_id, str)
            or not _KEY_ID.fullmatch(key_id)
            or status not in _STATUSES
            or not isinstance(encoded_key, str)
            or not isinstance(scopes, list)
            or not scopes
            or not all(isinstance(scope, str) and scope for scope in scopes)
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise PublisherTrustError(
                "publisher trust registry contains invalid publisher metadata"
            )
        if key_id in publishers:
            raise PublisherTrustError("publisher trust registry contains duplicate key identifiers")
        try:
            public_key = base64.b64decode(encoded_key, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise PublisherTrustError(
                "publisher trust registry contains an invalid public key"
            ) from exc
        if len(public_key) != 32 or hashlib.sha256(public_key).hexdigest() != digest:
            raise PublisherTrustError("publisher trust registry public-key digest does not match")
        publishers[key_id] = TrustedPublisher(
            key_id=key_id,
            public_key=public_key,
            publisher=str(entry.get("publisher", "")),
            status=status,
            plugin_id_prefixes=tuple(scopes),
        )
    if not publishers:
        raise PublisherTrustError("publisher trust registry must contain at least one publisher")
    return publishers


__all__ = ["PublisherTrustError", "load_trusted_publishers"]
