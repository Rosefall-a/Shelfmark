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


def test_sandboxed_frontend_can_coexist_with_declarative_host_contributions() -> None:
    data = document_data()
    data["frontend"] = {"entry": "frontend/index.html"}

    document = PluginUiDocument.model_validate(data)

    assert document.frontend is not None
    assert document.extensions[0].slot.value == "home.after-widgets"


def test_page_replacements_are_page_scoped_and_reference_declared_pages() -> None:
    data = document_data()
    data["page_replacements"] = [
        {"id": "replace-home", "page": "home", "page_id": "dashboard", "order": 1}
    ]
    document = PluginUiDocument.model_validate(data)

    assert document.page_replacements[0].page.value == "home"

    data["page_replacements"][0]["page"] = "everything"
    with pytest.raises(ValidationError):
        PluginUiDocument.model_validate(data)
