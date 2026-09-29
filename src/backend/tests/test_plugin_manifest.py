from src.plugin_api.contracts import PluginManifest


def test_manifest_accepts_bundled_frontend_declaration() -> None:
    manifest = PluginManifest.model_validate(
        {
            "manifest_version": 1,
            "plugin_id": "example.ui-playground",
            "name": "Plugin UI Playground",
            "version": "1.0.0",
            "description": "UI smoke test",
            "entrypoint": "plugin:main",
            "sdk_version_range": "^1.0.0",
            "application_version_range": "*",
            "capabilities": [{"name": "notifications.send", "version": 1}],
            "permissions": [
                {
                    "capability": {"name": "notifications.send", "version": 1},
                    "rationale": "Send page announcements.",
                }
            ],
            "dependencies": [],
            "ui": {"settings": ["filters"], "actions": ["announce-page"], "pages": ["overview"]},
            "storage": {"quota_mb": 1},
            "integrity": {
                "sha256": "0" * 64,
                "signature": None,
                "key_id": None,
            },
            "frontend": {"entry": "frontend/index.html"},
        }
    )

    assert manifest.frontend is not None
    assert manifest.frontend.entry == "frontend/index.html"


def test_manifest_without_frontend_remains_valid() -> None:
    manifest = PluginManifest.model_validate(
        {
            "plugin_id": "example.playtime-report",
            "name": "Playtime Report",
            "version": "1.0.0",
            "entrypoint": "plugin:main",
            "sdk_version_range": "^1.0.0",
            "application_version_range": "*",
            "integrity": {"sha256": "0" * 64, "signature": None, "key_id": None},
        }
    )

    assert manifest.frontend is None
