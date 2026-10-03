"""Playnite-style desktop integration with installation/user/device scope."""
from dataclasses import dataclass
from uuid import UUID

from src.plugin_api.contracts import Capability, CapabilityRef, GameRepresentation, PluginIdentity, RequestContext
from src.plugin_api.validation import ValidationGateway


@dataclass
class ExamplePlaynitePlugin:
    gateway: ValidationGateway
    plugin: PluginIdentity
    device_id: UUID

    def context(self, capability: Capability, user_id: UUID) -> RequestContext:
        from src.plugin_api.contracts import UserContext
        return RequestContext(
            request_id=UUID(int=0),
            application_id=UUID(int=1),
            gateway_id=UUID(int=2),
            plugin=self.plugin,
            user=UserContext(user_id=user_id),
            device_id=self.device_id,
            requested_capability=CapabilityRef(name=capability),
        )

    async def sync_game(self, user_id: UUID, game: GameRepresentation) -> GameRepresentation:
        context = self.context(Capability.GAMES_WRITE, user_id)
        self.gateway._authorize(context, Capability.GAMES_WRITE)
        return game
