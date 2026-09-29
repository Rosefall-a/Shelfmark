"""Discord-style event integration using the Plugin API gateway boundary."""
from dataclasses import dataclass, field
from uuid import UUID

from src.plugin_api.contracts import Capability, CapabilityRef, EventEnvelope, EventSubscription, PluginIdentity, RequestContext
from src.plugin_api.validation import ValidationGateway


@dataclass
class ExampleDiscordPlugin:
    gateway: ValidationGateway
    plugin: PluginIdentity
    linked_users: dict[str, UUID] = field(default_factory=dict)

    def context(self, capability: Capability, user_id: UUID | None = None) -> RequestContext:
        from src.plugin_api.contracts import UserContext
        return RequestContext(
            request_id=UUID(int=0),
            application_id=UUID(int=1),
            gateway_id=UUID(int=2),
            plugin=self.plugin,
            user=UserContext(user_id=user_id) if user_id else None,
            requested_capability=CapabilityRef(name=capability),
        )

    def link_user(self, discord_user_id: str, user_id: UUID) -> None:
        self.linked_users[discord_user_id] = user_id
        self.gateway.storage_put(
            self.context(Capability.PLUGIN_STORAGE, user_id),
            f"users/{discord_user_id}",
            str(user_id).encode(),
        )

    def subscribe(self, user_id: UUID) -> None:
        self.gateway.subscribe(
            self.context(Capability.EVENTS_SUBSCRIBE, user_id),
            EventSubscription(
                event_types=("game.updated", "notification.created"),
                user_ids=(user_id,),
            ),
        )

    def events(self) -> tuple[EventEnvelope[dict], ...]:
        return tuple(self.gateway.events[self.plugin.plugin_id])
