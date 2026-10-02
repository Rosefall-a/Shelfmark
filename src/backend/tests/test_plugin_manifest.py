from src.plugin_api.contracts import PluginManifest


def backend_manifest(**changes) -> dict:
    manifest = {
        "plugin_id": "example.backend",
        "name": "Backend Example",
        "version": "1.0.0",
        "entrypoint": "plugin:main",
        "sdk_version_range": "^1.0.0",
        "application_version_range": "*",
        "capabilities": [{"name": "backend.routes.plugin", "version": 1}],
        "permissions": [
            {
                "capability": {"name": "backend.routes.plugin", "version": 1},
                "rationale": "Serve an authenticated plugin API.",
            }
        ],
        "backend_routes": [
            {
                "id": "documents",
                "scope": "plugin",
                "path": "documents/{document_id}",
                "methods": ["GET"],
                "handler": "plugin:get_document",
            }
        ],
        "integrity": {"sha256": "0" * 64},
    }
    manifest.update(changes)
    return manifest


def test_manifest_accepts_namespaced_backend_route() -> None:
    manifest = PluginManifest.model_validate(backend_manifest())
    assert manifest.backend_routes[0].path == "documents/{document_id}"


def test_manifest_requires_route_capability() -> None:
    import pytest

    with pytest.raises(ValueError, match="backend.routes.plugin"):
        PluginManifest.model_validate(backend_manifest(capabilities=[], permissions=[]))


def test_manifest_rejects_reserved_or_overlapping_backend_routes() -> None:
    import pytest

    with pytest.raises(ValueError, match="host-owned"):
        PluginManifest.model_validate(
            backend_manifest(
                backend_routes=[
                    {
                        "id": "settings",
                        "path": "settings",
                        "handler": "plugin:settings",
                    }
                ]
            )
        )
    with pytest.raises(ValueError, match="conflicting"):
        PluginManifest.model_validate(
            backend_manifest(
                backend_routes=[
                    {
                        "id": "dynamic",
                        "path": "reports/{report_id}",
                        "handler": "plugin:dynamic",
                    },
                    {
                        "id": "current",
                        "path": "reports/current",
                        "handler": "plugin:current",
                    },
                ]
            )
        )


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


def test_manifest_rejects_unsafe_frontend_entry() -> None:
    import pytest

    with pytest.raises(ValueError):
        PluginManifest.model_validate(
            {
                "plugin_id": "example.ui-playground",
                "name": "Plugin UI Playground",
                "version": "1.0.0",
                "entrypoint": "plugin:main",
                "sdk_version_range": "^1.0.0",
                "application_version_range": "*",
                "integrity": {"sha256": "0" * 64, "signature": None, "key_id": None},
                "frontend": {"entry": "../index.html"},
            }
        )


def test_manifest_rejects_empty_frontend_entry() -> None:
    import pytest

    with pytest.raises(ValueError):
        PluginManifest.model_validate(
            {
                "plugin_id": "example.ui-playground",
                "name": "Plugin UI Playground",
                "version": "1.0.0",
                "entrypoint": "plugin:main",
                "sdk_version_range": "^1.0.0",
                "application_version_range": "*",
                "integrity": {"sha256": "0" * 64, "signature": None, "key_id": None},
                "frontend": {"entry": ""},
            }
        )


def test_ui_playground_manifest_contract_is_accepted() -> None:
    manifest = PluginManifest.model_validate(
        {
            "manifest_version": 1,
            "plugin_id": "example.ui-playground",
            "name": "Plugin UI Playground",
            "version": "1.0.0",
            "description": "Vue UI smoke test with four visible pages, filter controls, private Discord storage, and page announcements.",
            "entrypoint": "plugin:main",
            "sdk_version_range": "^1.0.0",
            "application_version_range": "*",
            "capabilities": [
                {"name": "notifications.send", "version": 1},
                {"name": "plugin.storage", "version": 1},
            ],
            "permissions": [
                {
                    "capability": {"name": "notifications.send", "version": 1},
                    "rationale": "Send the current page announcement to the configured Discord webhook.",
                },
                {
                    "capability": {"name": "plugin.storage", "version": 1},
                    "rationale": "Store the Discord webhook in private plugin storage.",
                },
            ],
            "dependencies": [],
            "ui": {
                "settings": ["filters", "discord"],
                "actions": ["announce-page"],
                "pages": ["overview", "library", "details", "diagnostics"],
            },
            "storage": {"quota_mb": 1},
            "integrity": {"sha256": "0" * 64, "signature": None, "key_id": None},
            "frontend": {"entry": "frontend/index.html"},
        }
    )
    assert manifest.plugin_id == "example.ui-playground"


def test_ui_playground_permissions_match_capabilities() -> None:
    manifest = PluginManifest.model_validate(
        {
            "manifest_version": 1,
            "plugin_id": "example.ui-playground",
            "name": "Plugin UI Playground",
            "version": "1.0.0",
            "entrypoint": "plugin:main",
            "sdk_version_range": "^1.0.0",
            "application_version_range": "*",
            "capabilities": [
                {"name": "notifications.send", "version": 1},
                {"name": "plugin.storage", "version": 1},
            ],
            "permissions": [
                {
                    "capability": {"name": "notifications.send", "version": 1},
                    "rationale": "announce",
                },
                {
                    "capability": {"name": "plugin.storage", "version": 1},
                    "rationale": "store webhook",
                },
            ],
            "integrity": {"sha256": "0" * 64, "signature": None, "key_id": None},
            "frontend": {"entry": "frontend/index.html"},
        }
    )
    capabilities = {(item.name, item.version) for item in manifest.capabilities}
    assert {
        (item.capability.name, item.capability.version) for item in manifest.permissions
    } <= capabilities
