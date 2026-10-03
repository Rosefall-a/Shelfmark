from __future__ import annotations

import logging
from urllib.parse import urlparse
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.crypto import decrypt_secret
from src.database.models.notification_provider_setting import NotificationProviderSetting
from src.database.models.user import User
from src.features.notification_providers.base import DeliveryResult, NotificationMessage, ProviderDestination

logger = logging.getLogger(__name__)
DISCORD_HOSTS = {"discord.com", "discordapp.com", "canary.discord.com", "ptb.discord.com"}

def validate_webhook_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    return parsed.scheme == "https" and parsed.hostname in DISCORD_HOSTS and parsed.path.startswith("/api/webhooks/") and len(parsed.path.split("/")) >= 4

class DiscordWebhookProvider:
    id = "discord"
    name = "Discord webhook"
    def available(self) -> bool:
        return True
    async def lookup_destination(self, db: AsyncSession, user: User, setting: NotificationProviderSetting | None) -> ProviderDestination | None:
        del db, user
        if setting is None or not setting.enabled or not setting.destination_secret:
            return None
        try:
            webhook = decrypt_secret(setting.destination_secret)
        except Exception:
            logger.warning("Discord notification credential could not be decrypted")
            return None
        if not validate_webhook_url(webhook):
            return None
        return ProviderDestination(webhook, "Discord webhook")
    def enabled_for_user(self, setting: NotificationProviderSetting | None) -> bool:
        return bool(setting and setting.enabled and setting.destination_secret)
    async def deliver(self, destination: ProviderDestination, message: NotificationMessage) -> DeliveryResult:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(destination.value, json={"content": f"**{message.title}**\n{message.body}"})
            if 200 <= response.status_code < 300:
                return DeliveryResult(True)
            logger.warning("Discord notification delivery failed with HTTP %s", response.status_code)
            return DeliveryResult(False, "Discord webhook delivery failed.")
        except (httpx.HTTPError, TimeoutError):
            logger.warning("Discord notification delivery failed")
            return DeliveryResult(False, "Discord webhook delivery failed.")
        except Exception:
            logger.warning("Unexpected Discord notification delivery failure")
            return DeliveryResult(False, "Discord webhook delivery failed.")

discord_provider = DiscordWebhookProvider()
