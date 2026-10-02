"""Rich release metadata must remain compatible with existing v1 catalogues."""

import pytest
import ast
import inspect
from pydantic import BaseModel, Field
from fastapi import HTTPException
from src.api.routes import plugins


def entry(**changes):
    return {
        "plugin_id": "example.metadata",
        "name": "Metadata",
        "version": "2.0.0",
        "url": "https://packages.example/plugin.utp",
        **changes,
    }


def test_packaged_icons_release_hashes_tags_and_documentation_are_preserved(monkeypatch):
    monkeypatch.setattr(plugins, "_validate_remote_url", lambda url: url)
    records = plugins._catalog_entries(
        {
            "version": 1,
            "plugins": [
                entry(
                    icon={"path": "icon.svg", "sha256": "a" * 64},
                    build={"source_path": "examples/metadata"},
                    publisher="Publisher",
                    sha256="b" * 64,
                    package_sha256="c" * 64,
                    automatic_update=False,
                    tags=["media", "integration"],
                    readme="# Plugin documentation",
                    sdk_version_range="^1.0.0",
                    application_version_range="^1.0.0",
                    package={"format": "utp-v1", "size_bytes": 1000},
                )
            ],
        },
        source_url="https://catalogue.example/list.json",
    )
    record = records[0]
    assert record["icon"] == "https://catalogue.example/examples/metadata/icon.svg"
    assert record["icon_metadata"]["sha256"] == "a" * 64
    assert record["digest"] == "b" * 64
    assert record["package_sha256"] == "c" * 64
    assert record["automatic_update"] is False
    assert record["tags"] == ("media", "integration")
    assert record["readme"].startswith("# Plugin")
    assert record["publisher"] == "Publisher"
    assert "^1.0.0" in record["compatibility"]


@pytest.mark.parametrize("path", ["../icon.svg", "/icon.svg", "a\\icon.svg", "a//icon.svg"])
def test_catalogue_rejects_unsafe_packaged_icon_paths(path):
    with pytest.raises(HTTPException) as error:
        plugins._catalog_entries(
            {"version": 1, "plugins": [entry(icon={"path": path, "sha256": "a" * 64})]}
        )
    assert error.value.status_code == 502


def test_old_catalogue_without_release_metadata_remains_supported(monkeypatch):
    monkeypatch.setattr(plugins, "_validate_remote_url", lambda url: url)
    record = plugins._catalog_entries({"version": 1, "plugins": [entry()]})[0]
    assert record["version"] == "2.0.0"
    assert record["automatic_update"] is True
    assert record["icon"] is None


def test_catalogue_transport_model_remains_loadable_by_public_contract_tools():
    # The independent plugin repository validates transport metadata without
    # importing the host API server or requiring its database configuration.
    namespace = {
        "BaseModel": BaseModel,
        "Field": Field,
        "PluginDependency": plugins.PluginDependency,
    }
    source = inspect.getsource(plugins.PluginCatalogEntry)
    exec(compile(ast.parse(source), "catalogue-contract", "exec"), namespace)
    model = namespace["PluginCatalogEntry"]
    validated = model.model_validate(
        entry(icon={"path": "icon.svg", "sha256": "a" * 64}, sha256="b" * 64)
    )
    assert validated.icon["path"] == "icon.svg"
    assert validated.digest == "b" * 64
    assert model.model_validate(entry(digest="c" * 64)).digest == "c" * 64
