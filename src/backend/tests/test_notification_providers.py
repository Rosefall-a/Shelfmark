import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.features.notification_providers.base import NotificationMessage
from src.features.notification_providers.discord import DiscordWebhookProvider, validate_webhook_url
from src.features.notification_providers.smtp import SMTPConfig, SMTPNotificationProvider


def test_provider_registry_has_initial_providers():
    from src.features.notification_providers.registry import PROVIDER_IDS
    assert PROVIDER_IDS == ("smtp", "discord")


def test_discord_webhook_validation_rejects_invalid_hosts_and_schemes():
    assert validate_webhook_url("https://" + "discord.com/api/webhooks/123/token")
    assert not validate_webhook_url("https://" + "example.com/api/webhooks/123/token")
    assert not validate_webhook_url("http://" + "discord.com/api/webhooks/123/token")
    assert not validate_webhook_url("https://" + "discord.com/channels/123")


def test_smtp_user_lookup_uses_existing_user_email():
    import asyncio
    provider = SMTPNotificationProvider(SMTPConfig(True, "smtp.example.test", 587, None, None, "from@example.test", "starttls"))
    user = type("User", (), {"email": "person@example.test"})()
    result = asyncio.run(provider.lookup_destination(None, user, None))
    assert result is not None
    assert result.value == "person@example.test"


@pytest.mark.asyncio
async def test_discord_delivery_failure_is_reported_without_raising():
    provider = DiscordWebhookProvider()
    message = NotificationMessage(uuid.uuid4(), "episode_aired", "Title", "Body", "tv", uuid.uuid4(), 1)
    with patch("src.features.notification_providers.discord.httpx.AsyncClient") as client:
        instance = client.return_value.__aenter__.return_value
        instance.post = AsyncMock(side_effect=TimeoutError())
        result = await provider.deliver(type("Destination", (), {"value": "https://discord.invalid"})(), message)
    assert not result.success
    assert result.error == "Discord webhook delivery failed."


@pytest.mark.asyncio
async def test_smtp_delivery_failure_is_reported_without_raising():
    config = SMTPConfig(True, "smtp.example.test", 587, "user", "secret", "from@example.test", "starttls")
    provider = SMTPNotificationProvider(config)
    message = NotificationMessage(uuid.uuid4(), "episode_aired", "Title", "Body", "tv", uuid.uuid4(), 1)
    with patch("src.features.notification_providers.smtp._send", side_effect=TimeoutError()):
        result = await provider.deliver(type("Destination", (), {"value": "to@example.test"})(), message)
    assert not result.success
    assert result.error == "SMTP delivery failed."


def test_provider_contract_separates_lookup_from_delivery():
    from src.features.notification_providers.base import NotificationProvider

    assert "lookup_destination" in getattr(NotificationProvider, "__annotations__", {}) or hasattr(NotificationProvider, "lookup_destination")
    assert "deliver" in getattr(NotificationProvider, "__annotations__", {}) or hasattr(NotificationProvider, "deliver")


@pytest.mark.asyncio
async def test_smtp_successful_delivery():
    provider = SMTPNotificationProvider(
        SMTPConfig(True, "smtp.example.test", 587, None, None, "from@example.test", "starttls")
    )
    message = NotificationMessage(uuid.uuid4(), "episode_aired", "Title", "Body", "tv", uuid.uuid4(), 1)
    with patch("src.features.notification_providers.smtp._send") as send:
        result = await provider.deliver(
            type("Destination", (), {"value": "to@example.test"})(), message
        )
    send.assert_called_once()
    assert result.success


@pytest.mark.asyncio
async def test_discord_successful_delivery():
    provider = DiscordWebhookProvider()
    message = NotificationMessage(uuid.uuid4(), "episode_aired", "Title", "Body", "tv", uuid.uuid4(), 1)
    with patch("src.features.notification_providers.discord.httpx.AsyncClient") as client:
        instance = client.return_value.__aenter__.return_value
        response = type("Response", (), {"status_code": 204})()
        instance.post = AsyncMock(return_value=response)
        result = await provider.deliver(
            type("Destination", (), {"value": "https://discord.com/api/webhooks/1/token"})(),
            message,
        )
    assert result.success


def test_smtp_rejects_invalid_security_and_recipient():
    provider = SMTPNotificationProvider(
        SMTPConfig(True, "smtp.example.test", 587, None, None, "from@example.test", "bogus")
    )
    user = type("User", (), {"email": "not-an-email"})()
    import asyncio
    assert asyncio.run(provider.lookup_destination(None, user, None)) is None
