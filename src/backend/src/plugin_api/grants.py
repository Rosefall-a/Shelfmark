"""Persistence-backed capability grant lookup shared by gateway consumers."""

from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.models.plugin_permissions import PluginPermissionGrant
from src.plugin_api.capabilities import capability_grant_candidates


def installation_is_executable(plugin: dict[str, Any]) -> bool:
    """Accept only affirmative live lifecycle metadata from the runtime registry."""
    return (
        plugin.get("enabled") is True
        and plugin.get("compatible") is True
        and plugin.get("status") in {"running", "completed", "stopped"}
        and plugin.get("health") in {"healthy", "unknown"}
    )


async def has_capability_grant(
    db: AsyncSession,
    *,
    plugin_id: str,
    installation_id: UUID,
    capability: str,
    user_id: UUID,
    capability_version: int = 1,
    device_id: UUID | None = None,
) -> bool:
    """Resolve a grant against the exact installation and authenticated user context."""
    grant = await db.scalar(
        select(PluginPermissionGrant.id).where(
            PluginPermissionGrant.plugin_id == plugin_id,
            PluginPermissionGrant.installation_id == installation_id,
            PluginPermissionGrant.capability.in_(capability_grant_candidates(capability)),
            PluginPermissionGrant.capability_version == capability_version,
            PluginPermissionGrant.revoked_at.is_(None),
            or_(
                PluginPermissionGrant.user_id.is_(None),
                PluginPermissionGrant.user_id == user_id,
            ),
            or_(
                PluginPermissionGrant.device_id.is_(None),
                PluginPermissionGrant.device_id == device_id,
            ),
        )
    )
    return grant is not None
