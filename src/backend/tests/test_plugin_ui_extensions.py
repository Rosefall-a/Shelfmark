"""Validation coverage for host-owned plugin navigation and extension slots."""

import pytest
from pydantic import ValidationError

from src.api.routes.plugins import _filter_ui_document
from src.plugin_api.contracts import Capability, PluginUiDocument


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


def test_native_and_host_contributions_are_filtered_by_effective_grants() -> None:
    data = document_data()
    data.update(
        {
            "frontend": {"entry": "frontend/index.html"},
            "native_frontend": {
                "entry": "native/index.js",
                "styles": ["native/style.css"],
            },
            "settings_sections": [
                {
                    "id": "sessions",
                    "label": "Sessions",
                    "page_id": "dashboard",
                }
            ],
            "overlays": [{"id": "help", "page_id": "dashboard"}],
        }
    )
    document = PluginUiDocument.model_validate(data)

    sandbox_only = _filter_ui_document(document, frozenset())
    assert sandbox_only.frontend is not None
    assert sandbox_only.native_frontend is None
    assert sandbox_only.extensions == ()
    assert sandbox_only.settings_sections == ()
    assert sandbox_only.overlays == ()

    privileged = _filter_ui_document(
        document,
        frozenset(
            {
                Capability.FRONTEND_NATIVE.value,
                Capability.FRONTEND_PAGE_EXTEND.value,
                Capability.FRONTEND_SETTINGS.value,
                Capability.FRONTEND_OVERLAY.value,
            }
        ),
    )
    assert privileged.native_frontend is not None
    assert privileged.extensions[0].id == "home-summary"
    assert privileged.settings_sections[0].id == "sessions"
    assert privileged.overlays[0].id == "help"


def test_navigation_targets_are_explicit_and_reference_declared_contributions() -> None:
    data = document_data()
    data["routes"] = [{"id": "sessions-route", "path": "sessions", "page_id": "dashboard"}]
    data["navigation"] = [
        {
            "id": "sessions-nav",
            "location": "main.sidebar",
            "label": "Sessions",
            "route_id": "sessions-route",
        }
    ]
    assert PluginUiDocument.model_validate(data).navigation[0].route_id == "sessions-route"

    data["navigation"][0]["page_id"] = "dashboard"
    with pytest.raises(ValidationError, match="exactly one"):
        PluginUiDocument.model_validate(data)
