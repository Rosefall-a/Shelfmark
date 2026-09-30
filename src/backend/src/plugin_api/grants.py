"""Persistence-backed capability grant lookup shared by gateway consumers."""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.plugin_permissions import PluginPermissionGrant


async def has_capability_grant(
    db: AsyncSession,
    *,
    plugin_id: str,
    installation_id: UUID,
    capability: str,
    user_id: UUID,
    capability_version: int = 1,
) -> bool:
    """Resolve a grant against the exact installation and authenticated user context."""
    grant = await db.scalar(
        select(PluginPermissionGrant.id).where(
            PluginPermissionGrant.plugin_id == plugin_id,
            PluginPermissionGrant.installation_id == installation_id,
            PluginPermissionGrant.capability == capability,
            PluginPermissionGrant.capability_version == capability_version,
            PluginPermissionGrant.revoked_at.is_(None),
            or_(
                PluginPermissionGrant.user_id.is_(None),
                PluginPermissionGrant.user_id == user_id,
            ),
        )
    )
    return grant is not None
