"""Minimal notification provider example using only the stable coordinator DTOs."""
from dataclasses import dataclass, field
from uuid import UUID

from src.plugin_api.coordinators import NotificationProvider, NotificationRequest, NotificationResult


@dataclass
class ExampleNotificationPlugin(NotificationProvider):
    api_version: str = "v1"
    delivered: list[UUID] = field(default_factory=list)

    async def send(self, request: NotificationRequest) -> NotificationResult:
        self.delivered.append(request.notification_id)
        return NotificationResult(
            delivered=True,
            external_id=f"example-notification:{request.notification_id}",
        )
