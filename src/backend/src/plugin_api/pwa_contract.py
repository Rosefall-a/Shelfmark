"""Inert PWA contribution validation independent of server configuration."""

import io
import json

from PIL import Image

from .contracts import PluginPwaDeclaration


def validate_pwa_assets(declaration: PluginPwaDeclaration, files: dict[str, bytes]) -> None:
    """Reject missing, executable, oversized or inconsistent public metadata."""
    raw = files[declaration.manifest]
    if len(raw) > 16 * 1024:
        raise ValueError("PWA manifest exceeds 16 KiB")
    manifest = json.loads(raw)
    if not isinstance(manifest, dict):
        raise ValueError("PWA manifest must be an object")
    for key in ("name", "short_name", "theme_color", "background_color"):
        if manifest.get(key) != getattr(declaration, key):
            raise ValueError("PWA metadata does not match its declaration")
    for key, value in {
        "id": "/",
        "scope": "/",
        "start_url": "/?pwa=1",
        "display": "standalone",
    }.items():
        if manifest.get(key) != value:
            raise ValueError("PWA manifest must launch the complete root application")
    for path, size in zip(declaration.icons, (192, 512), strict=True):
        content = files[path]
        if (
            len(content) > 256 * 1024
            or len(content) < 24
            or content[:8] != b"\x89PNG\r\n\x1a\n"
            or int.from_bytes(content[16:20], "big") != size
            or int.from_bytes(content[20:24], "big") != size
        ):
            raise ValueError("PWA icon must be a bounded, correctly sized PNG")
        with Image.open(io.BytesIO(content)) as icon:
            if icon.format != "PNG" or icon.size != (size, size):
                raise ValueError("PWA icon must be a correctly sized PNG")
            icon.verify()
