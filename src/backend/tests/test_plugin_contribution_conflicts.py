"""Contribution ownership is independent of installation/discovery order."""

from itertools import permutations

import pytest
from pydantic import ValidationError

from src.plugin_api import backend_routes
from src.plugin_api.backend_routes import BackendRouteConflictError, resolve_backend_route
from src.plugin_api.contracts import BackendRouteScope, PluginUiDocument


def route(path, scope="host", route_id="route"):
    return {"id": route_id, "scope": scope, "path": path, "handler": "contract:route"}


def test_reserved_host_conflicts_are_deterministic_for_disabled_and_quarantined_owners():
    owners = [
        {
            "plugin_id": "z.plugin",
            "enabled": False,
            "status": "disabled",
            "backend_routes": [route("/api/reports/{id}")],
        },
        {
            "plugin_id": "a.plugin",
            "enabled": False,
            "status": "quarantined",
            "backend_routes": [route("/api/reports/current")],
        },
    ]
    messages = []
    for ordered in permutations(owners):
        with pytest.raises(BackendRouteConflictError) as conflict:
            backend_routes.validate_host_route_ownership(ordered)
        messages.append(str(conflict.value))
        with pytest.raises(BackendRouteConflictError, match="a.plugin, z.plugin"):
            resolve_backend_route(
                ordered, scope=BackendRouteScope.HOST, path="/api/reports/current", method="GET"
            )
    assert len(set(messages)) == 1


def test_host_owned_routes_and_catchalls_cannot_be_claimed(monkeypatch):
    monkeypatch.setattr(
        backend_routes,
        "_host_routes",
        (
            ("/api/games/{game_id}", frozenset({"GET"})),
            ("/api/files/{path:path}", frozenset({"GET"})),
        ),
    )
    for path in ("/api/games/current", "/api/files/a/b/c"):
        with pytest.raises(BackendRouteConflictError, match="host-owned"):
            backend_routes.validate_host_route_ownership(
                [{"plugin_id": "contract", "backend_routes": [route(path)]}]
            )


def test_duplicate_namespaced_routes_fail_closed_in_either_order():
    routes = [route("items/{id}", "plugin", "first"), route("items/current", "plugin", "second")]
    for ordered in permutations(routes):
        with pytest.raises(BackendRouteConflictError):
            resolve_backend_route(
                [{"plugin_id": "contract", "backend_routes": ordered}],
                scope=BackendRouteScope.PLUGIN,
                plugin_id="contract",
                path="items/current",
                method="GET",
            )


@pytest.mark.parametrize("kind", ["navigation", "extensions", "routes"])
def test_duplicate_frontend_ids_are_rejected_in_either_order(kind):
    values = {
        "navigation": [
            {"id": "same", "location": "main.sidebar", "label": "First", "page_id": "first"},
            {"id": "same", "location": "main.sidebar", "label": "Second", "page_id": "second"},
        ],
        "extensions": [
            {"id": "same", "slot": "home.after-widgets", "page_id": "first"},
            {"id": "same", "slot": "game.overview.after-header", "page_id": "second"},
        ],
        "routes": [
            {"id": "same", "path": "first-path", "page_id": "first"},
            {"id": "same", "path": "second-path", "page_id": "second"},
        ],
    }
    for ordered in permutations(values[kind]):
        with pytest.raises(ValidationError, match="duplicate"):
            PluginUiDocument.model_validate(
                {
                    "plugin_id": "contract",
                    "title": "Contract",
                    "pages": [
                        {"id": "first", "title": "First"},
                        {"id": "second", "title": "Second"},
                    ],
                    kind: ordered,
                }
            )


def test_duplicate_route_paths_are_rejected_even_with_distinct_ids():
    with pytest.raises(ValidationError, match="duplicate plugin route path"):
        PluginUiDocument.model_validate(
            {
                "plugin_id": "contract",
                "title": "Contract",
                "pages": [{"id": "first", "title": "First"}],
                "routes": [
                    {"id": "one", "path": "same", "page_id": "first"},
                    {"id": "two", "path": "same", "page_id": "first"},
                ],
            }
        )
