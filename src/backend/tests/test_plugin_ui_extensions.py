"""Validation coverage for host-owned plugin navigation and extension slots."""

import pytest
from pydantic import ValidationError

from src.plugin_api.contracts import PluginUiDocument


def document_data() -> dict:
    return {
        "schema_version": "v1",
        "plugin_id": "example.extension",
        "title": "Example extension",
        "pages": [
            {
                "id": "dashboard",
                "title": "Dashboard",
                "navigation": {
                    "sidebar": True,
                    "label": "Example",
                    "order": 10,
                },
            }
        ],
        "extensions": [
            {
                "id": "home-summary",
                "slot": "home.after-widgets",
                "page_id": "dashboard",
                "order": 5,
            }
        ],
    }


def test_ui_document_accepts_allowlisted_navigation_and_extension_slots() -> None:
    document = PluginUiDocument.model_validate(document_data())

    assert document.pages[0].navigation is not None
    assert document.pages[0].navigation.sidebar
    assert document.extensions[0].slot.value == "home.after-widgets"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("slot", "game.detail.replace-header"),
        ("page_id", "missing"),
    ],
)
def test_ui_document_rejects_unknown_slots_and_pages(field: str, value: str) -> None:
    data = document_data()
    data["extensions"][0][field] = value

    with pytest.raises(ValidationError):
        PluginUiDocument.model_validate(data)


def test_custom_frontend_cannot_mount_in_host_page() -> None:
    data = document_data()
    data["frontend"] = {"entry": "frontend/index.html"}

    with pytest.raises(ValidationError):
        PluginUiDocument.model_validate(data)
