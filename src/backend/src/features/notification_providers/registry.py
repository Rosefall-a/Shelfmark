from sqlalchemy.ext.asyncio import AsyncSession
from src.features.notification_providers.base import NotificationProvider
from src.features.notification_providers.discord import discord_provider
from src.features.notification_providers.smtp import smtp_provider

async def get_notification_providers(db:AsyncSession)->dict[str,NotificationProvider]:
    return {"smtp":await smtp_provider(db),"discord":discord_provider}

async def get_notification_provider(db:AsyncSession,provider_id:str)->NotificationProvider|None:
    return (await get_notification_providers(db)).get(provider_id)
