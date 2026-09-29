"""Contract-level validation gateway used by integration examples."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from .contracts import (
    Capability,
    CapabilityRef,
    EventEnvelope,
    EventSubscription,
    GameRepresentation,
    PluginIdentity,
    RequestContext,
)
from .coordinators import (
    MetadataCandidate,
    MetadataProvider,
    MetadataProviderRequest,
    NotificationProvider,
    NotificationRequest,
    NotificationResult,
)
from .permissions import PermissionDecision, PermissionGrant, authorize_request


class ValidationGatewayError(RuntimeError):
    """Raised when an example integration crosses the gateway incorrectly."""


@dataclass
class ValidationGateway:
    """In-memory gateway harness exposing only Plugin API v1 contracts."""

    grants: tuple[PermissionGrant, ...]
    notifications: dict[str, NotificationProvider] = field(default_factory=dict)
    metadata: dict[str, MetadataProvider] = field(default_factory=dict)
    storage: dict[str, dict[str, bytes]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    subscriptions: dict[str, EventSubscription] = field(default_factory=dict)
    settings: dict[str, dict[str, str]] = field(default_factory=lambda: defaultdict(dict))
    events: dict[str, list[EventEnvelope[dict[str, Any]]]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def _authorize(self, context: RequestContext, capability: Capability) -> None:
        requested = context.requested_capability
        if requested.name is not capability:
            raise ValidationGatewayError(
                f"request declared {requested.name.value}, expected {capability.value}"
            )
        decision = authorize_request(context, self.grants)
        if decision.decision is not PermissionDecision.ALLOWED:
            raise ValidationGatewayError(decision.reason)

    async def send_notification(
        self, context: RequestContext, request: NotificationRequest
    ) -> NotificationResult:
        self._authorize(context, Capability.NOTIFICATIONS_SEND)
        provider = self.notifications.get(context.plugin.plugin_id)
        if provider is None:
            raise ValidationGatewayError("notification provider is not registered")
        return await provider.send(request)

    async def search_metadata(
        self, context: RequestContext, request: MetadataProviderRequest
    ) -> list[MetadataCandidate]:
        self._authorize(context, Capability.GAMES_READ)
        provider = self.metadata.get(context.plugin.plugin_id)
        if provider is None:
            raise ValidationGatewayError("metadata provider is not registered")
        return await provider.search(request)

    def subscribe(
        self, context: RequestContext, subscription: EventSubscription
    ) -> None:
        self._authorize(context, Capability.EVENTS_SUBSCRIBE)
        self.subscriptions[context.plugin.plugin_id] = subscription

    def publish_event(self, event: EventEnvelope[dict[str, Any]]) -> None:
        """Deliver only events matching each plugin subscription."""
        for plugin_id, subscription in self.subscriptions.items():
            if subscription.event_types and event.event_type not in subscription.event_types:
                continue
            if (
                subscription.user_ids
                and event.user_id is not None
                and event.user_id not in subscription.user_ids
            ):
                continue
            self.events[plugin_id].append(event)

    def storage_put(self, context: RequestContext, key: str, value: bytes) -> None:
        self._authorize(context, Capability.PLUGIN_STORAGE)
        self.storage[context.plugin.plugin_id][key] = bytes(value)

    def revoke(self, context: RequestContext) -> None:
        self.grants = tuple(
            grant
            for grant in self.grants
            if not (
                grant.plugin_id == context.plugin.plugin_id
                and grant.installation_id == context.plugin.installation_id
                and grant.capability.name is context.requested_capability.name
                and (grant.user_id is None or context.user is not None and grant.user_id == context.user.user_id)
            )
        )

    def settings_put(self, context: RequestContext, key: str, value: str) -> None:
        self._authorize(context, Capability.PLUGIN_SETTINGS)
        self.settings[context.plugin.plugin_id][key] = value

    def settings_get(self, context: RequestContext, key: str) -> str | None:
        self._authorize(context, Capability.PLUGIN_SETTINGS)
        return self.settings[context.plugin.plugin_id].get(key)

    def storage_get(self, context: RequestContext, key: str) -> bytes | None:
        self._authorize(context, Capability.PLUGIN_STORAGE)
        return self.storage[context.plugin.plugin_id].get(key)


@dataclass
class NotificationValidationPlugin(NotificationProvider):
    """Reference provider using the core-owned notification contract."""

    api_version: str = "v1"
    delivered: list[UUID] = field(default_factory=list)

    async def send(self, request: NotificationRequest) -> NotificationResult:
        self.delivered.append(request.notification_id)
        return NotificationResult(
            delivered=True,
            external_id=f"validation:{request.notification_id}",
            detail="delivered by validation provider",
        )


@dataclass
class MetadataValidationPlugin(MetadataProvider):
    """Reference provider returning normalized metadata DTOs."""

    api_version: str = "v1"
    candidates: tuple[MetadataCandidate, ...] = ()

    async def search(
        self, request: MetadataProviderRequest
    ) -> list[MetadataCandidate]:
        needle = request.query.casefold()
        return [
            candidate
            for candidate in self.candidates
            if needle in candidate.title.casefold()
        ]


@dataclass
class DiscordValidationPlugin:
    """Reference event integration with plugin-owned user mapping."""

    gateway: ValidationGateway
    plugin: PluginIdentity
    user_map: dict[str, UUID] = field(default_factory=dict)

    def context(
        self,
        capability: Capability,
        *,
        user_id: UUID | None = None,
    ) -> RequestContext:
        return RequestContext(
            request_id=UUID(int=0),
            application_id=UUID(int=1),
            gateway_id=UUID(int=2),
            plugin=self.plugin,
            user=(
                {"user_id": user_id, "authenticated": True}
                if user_id is not None
                else None
            ),
            requested_capability=CapabilityRef(name=capability),
        )

    async def link_user(self, discord_user_id: str, user_id: UUID) -> None:
        self.user_map[discord_user_id] = user_id
        self.gateway.storage_put(
            self.context(Capability.PLUGIN_STORAGE, user_id=user_id),
            f"users/{discord_user_id}",
            str(user_id).encode("ascii"),
        )

    def subscribe(self, user_id: UUID) -> None:
        self.gateway.subscribe(
            self.context(Capability.EVENTS_SUBSCRIBE, user_id=user_id),
            EventSubscription(
                event_types=("game.updated", "notification.created"),
                user_ids=(user_id,),
                max_events_per_minute=60,
            ),
        )

    def received_events(self) -> tuple[EventEnvelope[dict[str, Any]], ...]:
        return tuple(self.gateway.events[self.plugin.plugin_id])


@dataclass
class PlayniteValidationPlugin:
    """Reference desktop integration using scoped device identity."""

    gateway: ValidationGateway
    plugin: PluginIdentity
    device_id: UUID

    def context(self, capability: Capability, user_id: UUID) -> RequestContext:
        return RequestContext(
            request_id=UUID(int=0),
            application_id=UUID(int=1),
            gateway_id=UUID(int=2),
            plugin=self.plugin,
            user={"user_id": user_id, "authenticated": True},
            device_id=self.device_id,
            requested_capability=CapabilityRef(name=capability),
        )

    def validate_scoped_identity(self, user_id: UUID) -> RequestContext:
        return self.context(Capability.GAMES_READ, user_id)

    async def sync_game(
        self, user_id: UUID, game: GameRepresentation
    ) -> GameRepresentation:
        context = self.context(Capability.GAMES_WRITE, user_id)
        self.gateway._authorize(context, Capability.GAMES_WRITE)
        return game


def validation_event(
    *,
    event_type: str,
    user_id: UUID,
    payload: dict[str, Any],
) -> EventEnvelope[dict[str, Any]]:
    """Build a valid v1 event for the validation integrations."""
    return EventEnvelope(
        event_id=UUID(int=3),
        event_type=event_type,
        event_version=1,
        occurred_at=datetime.now(timezone.utc),
        source="validation-core",
        user_id=user_id,
        payload=payload,
    )


__all__ = [
    "DiscordValidationPlugin",
    "MetadataValidationPlugin",
    "NotificationValidationPlugin",
    "PlayniteValidationPlugin",
    "ValidationGateway",
    "ValidationGatewayError",
    "validation_event",
]
