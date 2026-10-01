"""Internal runtime-to-core Plugin API gateway for v1 workloads."""

from __future__ import annotations

import base64
import hmac
import mimetypes
import os
import time
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routes.settings import (
    get_or_create_app_integration_settings,
    get_or_create_scan_settings,
)
from src.core.integrations import resolve_integrations
from src.database.models.game import Game
from src.database.models.game_file_item import GameFileItem
from src.database.models.media_item import MediaItem
from src.database.models.movies import Movie, MovieStatus
from src.database.models.notification import Notification
from src.database.models.plugin_notification_provider import (
    PluginNotificationProviderRegistration,
)
from src.features.metadata.games.search import search_game_metadata
from src.features.notification_providers.delivery import ensure_deliveries
from src.plugin_api.capabilities import capability_implies
from src.plugin_api.contracts import (
    DocumentContentRepresentation,
    DocumentRepresentation,
    NotificationProviderRegistration,
)
from src.plugin_api.grants import has_capability_grant
from src.plugin_api.sessions import dispatch_sessions

_DATA_ROOT = Path("/data/users")
_MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
_TEXT_DOCUMENT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".log", ".rst", ".html", ".htm", ".xhtml"}
_METHOD_CAPABILITIES = {
    "games.list": "games.read",
    "games.metadata.search": "games.read",
    "documents.list": "documents.read",
    "documents.read": "documents.read",
    "sessions.list": "sessions.read",
    "sessions.revoke": "sessions.revoke",
    "sessions.revoke_all": "sessions.revoke",
    "sessions.admin.revoke_user": "sessions.admin.revoke",
    "sessions.geoip.status": "sessions.geoip.read",
    "sessions.admin.list": "sessions.admin.read",
    "sessions.admin.revoke": "sessions.admin.revoke",
    "sessions.admin.revoke_all": "sessions.admin.revoke",
    "media.list": "media.read",
    "media.import": "media.write",
    "events.poll": "events.subscribe",
    "notifications.send": "notifications.send",
    "notification_providers.register": "notification_providers.register",
    "notification_providers.unregister": "notification_providers.register",
}


def runtime_token_is_valid(token: str | None) -> bool:
    configured = os.getenv("PLUGIN_RUNTIME_TOKEN", "")
    if not configured or not token:
        return False
    return hmac.compare_digest(configured, token)


def _document_path(game: Game, item: GameFileItem) -> Path:
    if not game.folder_location or item.kind != "doc":
        raise LookupError("document not found")
    document_root = (
        _DATA_ROOT / str(game.user_id) / "games" / game.folder_location / "docs"
    ).resolve()
    candidate = (document_root / item.filename).resolve()
    try:
        candidate.relative_to(document_root)
    except ValueError as exc:
        raise LookupError("document not found") from exc
    if not candidate.is_file():
        raise LookupError("document not found")
    return candidate


def _document_media_type(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        with path.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise ValueError("document is not a valid PDF")
        return "application/pdf"
    if path.suffix.lower() not in _TEXT_DOCUMENT_EXTENSIONS:
        raise ValueError("document type is not supported")
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("text document is not valid UTF-8") from exc
    if any(ord(character) < 32 and character not in "\n\r\t" for character in text):
        raise ValueError("text document contains binary control characters")
    return "text/html" if path.suffix.lower() in {".html", ".htm", ".xhtml"} else "text/plain"


def _document_dto(game: Game, item: GameFileItem, path: Path) -> DocumentRepresentation:
    return DocumentRepresentation(
        id=item.id,
        game_id=game.id,
        game_title=game.title,
        filename=item.filename,
        media_type=mimetypes.guess_type(item.filename)[0] or "application/octet-stream",
        size_bytes=path.stat().st_size,
        created_at=item.created_at,
    )


async def dispatch_gateway_request(
    db: AsyncSession,
    *,
    plugin_id: str,
    installation_id: UUID,
    user_id: UUID,
    method: str,
    capability: str,
    payload: dict[str, Any],
    capability_version: int = 1,
) -> dict[str, Any]:
    required_capability = capability if method == "capabilities.check" else _METHOD_CAPABILITIES.get(method)
    if required_capability is None:
        raise ValueError(f"unsupported plugin gateway method: {method}")
    try:
        authorizes_method = capability_implies(capability, required_capability)
    except ValueError:
        authorizes_method = False
    if not authorizes_method:
        raise PermissionError(f"method {method} requires capability {required_capability}")
    if not await has_capability_grant(
        db,
        plugin_id=plugin_id,
        installation_id=installation_id,
        capability=capability,
        user_id=user_id,
        capability_version=capability_version,
    ):
        raise PermissionError(f"permission {capability} has not been granted")

    if method == "capabilities.check":
        return {"authorized": True}

    if method == "media.list":
        limit = max(1, min(int(payload.get("limit", 100)), 200))
        media = (await db.execute(select(Movie).where(Movie.user_id == user_id, Movie.deleted_at.is_(None)).order_by(Movie.sort_title, Movie.title).limit(limit))).scalars().all()
        return {"media": [{"id": str(item.id), "title": item.title, "media_type": "movie", "runtime_minutes": item.runtime_minutes, "poster_url": item.poster_url, "status": item.status.value if hasattr(item.status, "value") else str(item.status), "play_count": item.rewatches, "release_date": item.release_date.isoformat() if item.release_date else None, "updated_at": item.updated_at} for item in media]}

    if method == "games.list":
        limit = max(1, min(int(payload.get("limit", 50)), 200))
        games = (
            (
                await db.execute(
                    select(Game)
                    .where(Game.user_id == user_id, Game.deleted_at.is_(None))
                    .order_by(Game.sort_title, Game.title)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return {
            "games": [
                {
                    "id": str(game.id),
                    "title": game.title,
                    "name": game.title,
                    "status": game.status.value
                    if hasattr(game.status, "value")
                    else str(game.status),
                    "playtime_seconds": game.playtime_seconds,
                    "playtime_minutes": game.playtime_seconds // 60,
                    "last_played_at": game.last_played_at,
                    "last_played": game.last_played_at,
                    "rating_overall": float(game.rating_overall)
                    if game.rating_overall is not None
                    else None,
                }
                for game in games
            ]
        }

    if method == "games.metadata.search":
        query = str(payload.get("query", "")).strip()
        if not query:
            raise ValueError("metadata search query is required")
        limit = max(1, min(int(payload.get("limit", 10)), 20))
        scan = await get_or_create_scan_settings(user_id, db)
        preferences = {
            "provider_order": scan.provider_order,
            "image_provider_order": scan.image_provider_order,
            "save_developer": scan.save_developer,
            "save_publisher": scan.save_publisher,
            "save_series": scan.save_series,
            "save_tags": scan.save_tags,
            "save_features": scan.save_features,
            "save_description": scan.save_description,
            "save_age_rating": scan.save_age_rating,
            "save_release_date": scan.save_release_date,
            "save_time_to_beat": scan.save_time_to_beat,
            "save_key_art": scan.save_key_art,
            "save_banner": scan.save_banner,
            "save_logo": scan.save_logo,
            "save_icon": scan.save_icon,
        }
        integrations = resolve_integrations(await get_or_create_app_integration_settings(db))
        metadata_result = search_game_metadata(
            query,
            limit,
            None,
            preferences,
            None,
            integrations.igdb_client_id,
            integrations.igdb_client_secret,
        )
        return {"results": metadata_result.get("results", [])}

    if method == "documents.list":
        limit = max(1, min(int(payload.get("limit", 50)), 200))
        document_rows = (
            await db.execute(
                select(GameFileItem, Game)
                .join(Game, Game.id == GameFileItem.game_id)
                .where(
                    Game.user_id == user_id,
                    Game.deleted_at.is_(None),
                    GameFileItem.kind == "doc",
                    GameFileItem.deleted_at.is_(None),
                )
                .order_by(Game.sort_title, GameFileItem.filename)
                .limit(limit)
            )
        ).all()
        documents = []
        for item, game in document_rows:
            try:
                path = _document_path(game, item)
            except LookupError:
                continue
            documents.append(_document_dto(game, item, path).model_dump(mode="json"))
        return {"documents": documents}

    if method == "documents.read":
        try:
            document_id = UUID(str(payload.get("document_id", "")))
        except ValueError as exc:
            raise ValueError("document_id must be a UUID") from exc
        row = (
            await db.execute(
                select(GameFileItem, Game)
                .join(Game, Game.id == GameFileItem.game_id)
                .where(
                    GameFileItem.id == document_id,
                    GameFileItem.kind == "doc",
                    GameFileItem.deleted_at.is_(None),
                    Game.user_id == user_id,
                    Game.deleted_at.is_(None),
                )
            )
        ).one_or_none()
        if row is None:
            raise LookupError("document not found")
        item, game = row
        path = _document_path(game, item)
        if path.stat().st_size > _MAX_DOCUMENT_BYTES:
            raise ValueError("document exceeds the 5 MiB Plugin API limit")
        media_type = _document_media_type(path)
        document = _document_dto(game, item, path).model_copy(update={"media_type": media_type})
        content = DocumentContentRepresentation(
            document=document,
            encoding="base64",
            content=base64.b64encode(path.read_bytes()).decode("ascii"),
        )
        return content.model_dump(mode="json")

    if method.startswith("sessions."):
        return await dispatch_sessions(db, user_id=user_id, method=method, payload=payload)

    if method == "media.import":
        imported = []
        for item in payload.get("items", []):
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            movie = await db.scalar(select(Movie).where(Movie.user_id == user_id, Movie.deleted_at.is_(None), Movie.source == "jellyfin", Movie.title == title))
            if movie is None:
                movie = Movie(user_id=user_id, title=title, sort_title=title.lower(), source="jellyfin")
                db.add(movie)
            movie.runtime_minutes = item.get("runtime_minutes")
            movie.genres = list(item.get("genres") or [])
            if item.get("poster_url"):
                movie.poster_url = str(item["poster_url"])
            if item.get("played"):
                movie.status = MovieStatus.WATCHED
            imported.append({"id": str(movie.id), "title": movie.title, "external_id": item.get("external_id")})
        await db.commit()
        return {"imported": imported}

    if method == "events.poll":
        limit = max(1, min(int(payload.get("limit", 50)), 200))
        since = max(0, int(payload.get("since", 0)))
        events: list[dict[str, Any]] = []
        games = (await db.execute(select(Game).where(Game.user_id == user_id, Game.deleted_at.is_(None), Game.updated_at > since).order_by(Game.updated_at).limit(limit))).scalars().all()
        for game in games:
            events.append({"event_id": str(uuid5(NAMESPACE_URL, f"plugin-event:game.updated:{game.id}:{game.updated_at}")), "event_type": "game.updated", "event_version": 1, "occurred_at": game.updated_at, "source": "unnamed-tracking", "user_id": str(user_id), "payload": {"game_id": str(game.id), "title": game.title, "updated_at": game.updated_at}})
        if len(events) < limit:
            media_items = (await db.execute(select(MediaItem).join(Game, Game.id == MediaItem.game_id).where(Game.user_id == user_id, MediaItem.deleted_at.is_(None), MediaItem.created_at > since).order_by(MediaItem.created_at).limit(limit - len(events)))).scalars().all()
            for item in media_items:
                events.append({"event_id": str(uuid5(NAMESPACE_URL, f"plugin-event:media.added:{item.id}:{item.created_at}")), "event_type": "media.added", "event_version": 1, "occurred_at": item.created_at, "source": "unnamed-tracking", "user_id": str(user_id), "payload": {"media_id": str(item.id), "game_id": str(item.game_id), "kind": item.kind, "filename": item.filename, "created_at": item.created_at}})
        events.sort(key=lambda event: int(event["occurred_at"]))
        return {"events": events[:limit], "cursor": max([since, *[int(event["occurred_at"]) for event in events]])}

    if method == "notifications.send":
        title = str(payload.get("title", "")).strip()
        body = str(payload.get("body", "")).strip()
        if not title or not body:
            raise ValueError("notification title and body are required")
        notification = Notification(
            user_id=user_id,
            kind="plugin",
            media_type="plugin",
            media_id=uuid5(NAMESPACE_URL, f"unnamed-tracking:plugin:{plugin_id}"),
            title=title[:500],
            body=body[:10000],
            event_at=int(time.time()),
            dedupe_key=f"plugin:{plugin_id}:{time.time_ns()}",
        )
        db.add(notification)
        await db.flush()
        await ensure_deliveries(db, [notification.id])
        await db.commit()
        return {"sent": True, "notification_id": str(notification.id)}

    if method == "notification_providers.register":
        try:
            registration = NotificationProviderRegistration.model_validate(payload)
        except ValidationError as exc:
            raise ValueError("notification provider registration is invalid") from exc
        expected_prefix = f"{plugin_id}."
        if not registration.provider_id.startswith(expected_prefix):
            raise ValueError(f"provider_id must start with {expected_prefix}")
        existing = await db.scalar(
            select(PluginNotificationProviderRegistration).where(
                PluginNotificationProviderRegistration.provider_id == registration.provider_id
            )
        )
        if existing is not None and (
            existing.plugin_id != plugin_id or existing.installation_id != installation_id
        ):
            raise ValueError("notification provider ID is already registered")
        if existing is None:
            existing = PluginNotificationProviderRegistration(
                plugin_id=plugin_id,
                installation_id=installation_id,
                provider_id=registration.provider_id,
                name=registration.name,
                action_id=registration.action_id,
            )
            db.add(existing)
        else:
            existing.name = registration.name
            existing.action_id = registration.action_id
            existing.revoked_at = None
        await db.commit()
        return {
            "registered": True,
            "provider": registration.model_dump(mode="json"),
        }

    if method == "notification_providers.unregister":
        provider_id = str(payload.get("provider_id", ""))
        row = await db.scalar(
            select(PluginNotificationProviderRegistration).where(
                PluginNotificationProviderRegistration.plugin_id == plugin_id,
                PluginNotificationProviderRegistration.installation_id == installation_id,
                PluginNotificationProviderRegistration.provider_id == provider_id,
                PluginNotificationProviderRegistration.revoked_at.is_(None),
            )
        )
        if row is None:
            raise LookupError("notification provider registration not found")
        row.revoked_at = int(time.time())
        await db.commit()
        return {"unregistered": True, "provider_id": provider_id}

    raise ValueError(f"unsupported plugin gateway method: {method}")
