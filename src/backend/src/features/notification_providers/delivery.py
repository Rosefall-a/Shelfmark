from __future__ import annotations

import logging
import time
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.preferences import load_preferences
from src.database.models.notification import Notification
from src.database.models.notification_delivery import NotificationDelivery
from src.database.models.notification_provider_setting import NotificationProviderSetting
from src.database.models.user import User
from src.features.notification_providers.base import notification_message
from src.features.notification_providers.registry import get_notification_providers

logger=logging.getLogger(__name__)
MAX_ATTEMPTS=3

async def ensure_deliveries(db:AsyncSession, notification_id):
    providers=await get_notification_providers(db)
    existing={x.provider_id for x in (await db.execute(select(NotificationDelivery).where(NotificationDelivery.notification_id==notification_id))).scalars()}
    for provider_id in providers:
        if provider_id not in existing:
            db.add(NotificationDelivery(notification_id=notification_id,provider_id=provider_id,status="pending",attempts=0,next_attempt_at=int(time.time())))
    await db.flush()

async def process_pending_deliveries(db:AsyncSession, limit:int=50)->int:
    now=int(time.time())
    rows=(await db.execute(select(NotificationDelivery).where(NotificationDelivery.status.in_(["pending","retry"]),NotificationDelivery.next_attempt_at<=now).order_by(NotificationDelivery.next_attempt_at).limit(limit).with_for_update(skip_locked=True))).scalars().all()
    if not rows:return 0
    providers=await get_notification_providers(db)
    done=0
    for delivery in rows:
        notification=await db.get(Notification,delivery.notification_id)
        if notification is None: delivery.status="failed"; continue
        provider=providers.get(delivery.provider_id)
        if provider is None: delivery.status="failed"; delivery.last_error="Provider is unavailable."; continue
        user=await db.get(User,notification.user_id)
        if user is None: delivery.status="failed"; continue
        prefs=await load_preferences(db,user.id)
        if not any((prefs.get("notify_episode_aired") and notification.kind=="episode_aired",prefs.get("notify_season_started") and notification.kind=="season_started",prefs.get("notify_sequel_announced") and notification.kind=="sequel_announced",prefs.get("notify_movie_released") and notification.kind=="movie_released")):
            delivery.status="skipped"; continue
        setting=await db.scalar(select(NotificationProviderSetting).where(NotificationProviderSetting.user_id==user.id,NotificationProviderSetting.provider_id==delivery.provider_id))
        if not provider.enabled_for_user(setting):
            delivery.status="skipped"; continue
        destination=await provider.lookup_destination(db,user,setting)
        if destination is None:
            delivery.status="skipped"; continue
        delivery.attempts+=1; delivery.attempted_at=now
        result=await provider.deliver(destination,notification_message(notification))
        if result.success:
            delivery.status="sent"; delivery.last_error=None; done+=1
        elif delivery.attempts>=MAX_ATTEMPTS:
            delivery.status="failed"; delivery.last_error=result.error
        else:
            delivery.status="retry"; delivery.last_error=result.error; delivery.next_attempt_at=now + 60*(2**(delivery.attempts-1))
    await db.commit()
    return done
