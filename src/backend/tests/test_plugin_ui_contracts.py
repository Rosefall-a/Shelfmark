"""Regression tests for the versioned declarative plugin UI protocol."""

import pytest
from pydantic import ValidationError

from src.plugin_api.contracts import (
    Capability,
    CapabilityRef,
    PluginUiDocument,
    UiAction,
    UiField,
    UiFieldType,
    UiMenuItem,
    UiOption,
    UiPage,
    UiSettingsSection,
    UiValidation,
)


def _field(**overrides):
    values = {
        "id": "api-key",
        "label": "API key",
        "type": UiFieldType.PASSWORD,
        "secret": True,
        "required": True,
    }
    values.update(overrides)
    return UiField(**values)


def test_secret_fields_cannot_expose_defaults() -> None:
    with pytest.raises(ValidationError):
        _field(default="should-not-leak")


def test_select_fields_require_static_options() -> None:
    with pytest.raises(ValidationError):
        _field(id="provider", label="Provider", type=UiFieldType.SELECT, secret=False)


def test_validation_bounds_are_ordered() -> None:
    with pytest.raises(ValidationError):
        UiValidation(minimum=10, maximum=1)


def test_document_rejects_dangling_menu_and_page_references() -> None:
    with pytest.raises(ValidationError):
        PluginUiDocument(
            plugin_id="example.plugin",
            title="Example",
            menus=(UiMenuItem(id="open", label="Open", page_id="missing"),),
        )


def test_document_accepts_versioned_native_primitives() -> None:
    document = PluginUiDocument(
        plugin_id="example.plugin",
        title="Example",
        settings=(
            UiSettingsSection(
                id="general",
                title="General",
                fields=(
                    UiField(
                        id="enabled",
                        label="Enabled",
                        type=UiFieldType.BOOLEAN,
                        default=True,
                    ),
                    UiField(
                        id="provider",
                        label="Provider",
                        type=UiFieldType.SELECT,
                        options=(
                            UiOption(value="one", label="Provider One"),
                            UiOption(value="two", label="Provider Two"),
                        ),
                    ),
                ),
            ),
        ),
        actions=(
            UiAction(
                id="refresh",
                label="Refresh",
                capability=CapabilityRef(name=Capability.PLUGIN_SETTINGS, version=1),
            ),
        ),
        pages=(UiPage(id="settings", title="Settings", settings=("general",), actions=("refresh",)),),
        menus=(UiMenuItem(id="settings", label="Settings", page_id="settings"),),
    )
    assert document.schema_version.value == "v1"
    assert document.pages[0].settings == ("general",)


def test_field_defaults_match_declared_types() -> None:
    with pytest.raises(ValidationError):
        _field(type=UiFieldType.BOOLEAN, secret=False, default="yes")
    with pytest.raises(ValidationError):
        _field(type=UiFieldType.NUMBER, secret=False, default=True)


def test_select_and_multiselect_defaults_use_declared_options() -> None:
    with pytest.raises(ValidationError):
        _field(
            id="provider",
            label="Provider",
            type=UiFieldType.SELECT,
            secret=False,
            options=(UiOption(value="one", label="One"),),
            default="two",
        )
    with pytest.raises(ValidationError):
        _field(
            id="providers",
            label="Providers",
            type=UiFieldType.MULTISELECT,
            secret=False,
            options=(UiOption(value="one", label="One"),),
            default=("one", "two"),
        )


def test_select_options_must_be_unique() -> None:
    with pytest.raises(ValidationError):
        _field(
            id="provider",
            label="Provider",
            type=UiFieldType.SELECT,
            secret=False,
            options=(
                UiOption(value="one", label="One"),
                UiOption(value="one", label="Duplicate"),
            ),
        )


def test_invalid_regex_patterns_are_rejected() -> None:
    with pytest.raises(ValidationError):
        UiValidation(pattern="[")
