"""Internal runtime-to-core Plugin API gateway for v1 workloads."""

from __future__ import annotations

import hmac
import os
import time
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routes.settings import get_or_create_app_integration_settings, get_or_create_scan_settings
from src.core.integrations import resolve_integrations
from src.database.models.game import Game
from src.database.models.notification import Notification
from src.database.models.plugin_permissions import PluginPermissionGrant
from src.features.metadata.games.search import search_game_metadata


def runtime_token_is_valid(token: str | None) -> bool:
    configured = os.getenv("PLUGIN_RUNTIME_TOKEN", "")
    return bool(configured) and bool(token) and hmac.compare_digest(configured, token)


async def dispatch_gateway_request(
    db: AsyncSession,
    *,
    plugin_id: str,
    user_id: UUID,
    method: str,
    capability: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    grant = await db.scalar(
        select(PluginPermissionGrant.id).where(
            PluginPermissionGrant.plugin_id == plugin_id,
            PluginPermissionGrant.capability == capability,
            PluginPermissionGrant.revoked_at.is_(None),
        )
    )
    if grant is None:
        raise PermissionError(f"permission {capability} has not been granted")

    if method == "games.list":
        limit = max(1, min(int(payload.get("limit", 50)), 200))
        rows = (
            (await db.execute(
                select(Game)
                .where(Game.user_id == user_id, Game.deleted_at.is_(None))
                .order_by(Game.sort_title, Game.title)
                .limit(limit)
            ))
            .scalars()
            .all()
        )
        return {"games": [{
            "id": str(game.id), "title": game.title, "name": game.title,
            "status": game.status.value if hasattr(game.status, "value") else str(game.status),
            "playtime_seconds": game.playtime_seconds, "playtime_minutes": game.playtime_seconds // 60,
            "last_played_at": game.last_played_at, "last_played": game.last_played_at,
            "rating_overall": float(game.rating_overall) if game.rating_overall is not None else None,
        } for game in rows]}

    if method == "games.metadata.search":
        query = str(payload.get("query", "")).strip()
        if not query:
            raise ValueError("metadata search query is required")
        limit = max(1, min(int(payload.get("limit", 10)), 20))
        scan = await get_or_create_scan_settings(user_id, db)
        preferences = {
            "provider_order": scan.provider_order, "image_provider_order": scan.image_provider_order,
            "save_developer": scan.save_developer, "save_publisher": scan.save_publisher,
            "save_series": scan.save_series, "save_tags": scan.save_tags, "save_features": scan.save_features,
            "save_description": scan.save_description, "save_age_rating": scan.save_age_rating,
            "save_release_date": scan.save_release_date, "save_time_to_beat": scan.save_time_to_beat,
            "save_key_art": scan.save_key_art, "save_banner": scan.save_banner,
            "save_logo": scan.save_logo, "save_icon": scan.save_icon,
        }
        integrations = resolve_integrations(await get_or_create_app_integration_settings(db))
        result = await search_game_metadata(query, limit, None, preferences, None, integrations.igdb_client_id, integrations.igdb_client_secret)
        return {"results": result.get("results", [])}

    if method == "notifications.send":
        title = str(payload.get("title", "")).strip()
        body = str(payload.get("body", "")).strip()
        if not title or not body:
            raise ValueError("notification title and body are required")
        notification = Notification(
            user_id=user_id, kind="plugin", media_type="plugin",
            media_id=uuid5(NAMESPACE_URL, f"unnamed-tracking:plugin:{plugin_id}"),
            title=title[:500], body=body[:10000], event_at=int(time.time()),
            dedupe_key=f"plugin:{plugin_id}:{time.time_ns()}",
        )
        db.add(notification)
        await db.commit()
        return {"sent": True, "notification_id": str(notification.id)}

    raise ValueError(f"unsupported plugin gateway method: {method}")
