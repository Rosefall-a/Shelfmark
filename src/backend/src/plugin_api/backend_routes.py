"""Host-owned matching and ownership rules for plugin backend routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from pydantic import ValidationError

from .contracts import BackendRouteScope, PluginBackendRoute

_host_routes: tuple[tuple[str, frozenset[str]], ...] = ()


def reserve_host_routes(routes: Iterable[tuple[str, frozenset[str]]]) -> None:
    """Record the real host router's paths for installation conflict validation."""
    global _host_routes
    _host_routes = tuple(sorted(routes, key=lambda item: item[0]))


class BackendRouteConflictError(ValueError):
    """Raised when more than one installed plugin claims the same request."""


@dataclass(frozen=True, slots=True)
class ResolvedBackendRoute:
    """One declared route plus its authoritative installation owner."""

    plugin: dict[str, Any]
    route: PluginBackendRoute
    path_parameters: dict[str, str]


def route_paths_overlap(left: str, right: str) -> bool:
    """Return whether two literal/parameter paths can match the same URL."""

    left_parts = left.strip("/").split("/")
    right_parts = right.strip("/").split("/")
    for left_part, right_part in zip(left_parts, right_parts, strict=False):
        if left_part.endswith(":path}") or right_part.endswith(":path}"):
            return True
        if left_part != right_part and not (
            left_part.startswith("{") or right_part.startswith("{")
        ):
            return False
    return len(left_parts) == len(right_parts)


def match_route_path(declared: str, requested: str) -> dict[str, str] | None:
    """Match a declared route without allowing catch-all or traversal semantics."""

    declared_parts = declared.strip("/").split("/")
    requested_parts = requested.strip("/").split("/")
    if len(declared_parts) != len(requested_parts):
        return None
    parameters: dict[str, str] = {}
    for expected, actual in zip(declared_parts, requested_parts, strict=True):
        if not actual or actual in {".", ".."}:
            return None
        if expected.startswith("{"):
            parameters[expected[1:-1]] = actual
        elif expected != actual:
            return None
    return parameters


def plugin_backend_routes(plugin: dict[str, Any]) -> tuple[PluginBackendRoute, ...]:
    """Validate runtime-supplied declarations before they affect host routing."""

    raw_routes = plugin.get("backend_routes", ())
    if not isinstance(raw_routes, (list, tuple)):
        return ()
    try:
        return tuple(PluginBackendRoute.model_validate(route) for route in raw_routes)
    except ValidationError:
        return ()


def validate_host_route_ownership(
    plugins: Iterable[dict[str, Any]],
    candidate_plugin_id: str | None = None,
    candidate_routes: Iterable[PluginBackendRoute] = (),
) -> None:
    """Reject overlapping host route ownership across installed packages."""

    owners: list[tuple[str, PluginBackendRoute]] = []
    for plugin in plugins:
        plugin_id = str(plugin.get("plugin_id", ""))
        if candidate_plugin_id is not None and plugin_id == candidate_plugin_id:
            continue
        owners.extend(
            (plugin_id, route)
            for route in plugin_backend_routes(plugin)
            if route.scope is BackendRouteScope.HOST
        )
    if candidate_plugin_id is not None:
        owners.extend(
            (candidate_plugin_id, route)
            for route in candidate_routes
            if route.scope is BackendRouteScope.HOST
        )
    owners.sort(key=lambda item: (item[0], item[1].path, item[1].id))
    for plugin_id, route in owners:
        for path, methods in _host_routes:
            if set(route.methods).intersection(methods) and route_paths_overlap(route.path, path):
                raise BackendRouteConflictError(
                    f"host route {route.path} from {plugin_id} overlaps host-owned route {path}"
                )
    for index, (plugin_id, route) in enumerate(owners):
        for other_plugin_id, other_route in owners[index + 1 :]:
            if not set(route.methods).intersection(other_route.methods):
                continue
            if route_paths_overlap(route.path, other_route.path):
                raise BackendRouteConflictError(
                    f"host route {route.path} is claimed by both {plugin_id} and {other_plugin_id}"
                )


def resolve_backend_route(
    plugins: Iterable[dict[str, Any]],
    *,
    scope: BackendRouteScope,
    path: str,
    method: str,
    plugin_id: str | None = None,
) -> ResolvedBackendRoute | None:
    """Resolve one request while treating disabled packages as route owners."""

    matches: list[ResolvedBackendRoute] = []
    for plugin in plugins:
        owner_id = str(plugin.get("plugin_id", ""))
        if plugin_id is not None and owner_id != plugin_id:
            continue
        for route in plugin_backend_routes(plugin):
            if route.scope is not scope or method not in route.methods:
                continue
            parameters = match_route_path(route.path, path)
            if parameters is not None:
                matches.append(ResolvedBackendRoute(plugin, route, parameters))
    if len(matches) > 1:
        owners = ", ".join(sorted(str(match.plugin.get("plugin_id")) for match in matches))
        raise BackendRouteConflictError(f"backend route has conflicting owners: {owners}")
    return matches[0] if matches else None


__all__ = [
    "BackendRouteConflictError",
    "ResolvedBackendRoute",
    "match_route_path",
    "plugin_backend_routes",
    "reserve_host_routes",
    "resolve_backend_route",
    "route_paths_overlap",
    "validate_host_route_ownership",
]
