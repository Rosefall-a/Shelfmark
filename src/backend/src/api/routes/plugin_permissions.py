"""Administrative plugin permission and user-scoped client identity API."""

from __future__ import annotations

import hashlib
import time
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import get_current_admin, get_current_user
from src.database.models.plugin_permissions import PluginClientIdentity, PluginPermissionGrant, PluginPermissionRequest
from src.database.models.user import User
from src.database.session import get_db
from src.plugin_api.contracts import Capability
from src.plugin_api.permissions import issue_client_credential

router = APIRouter(prefix="/api/plugin-permissions", tags=["plugin-permissions"])


class PermissionRequestIn(BaseModel):
    plugin_id: str = Field(min_length=1, max_length=128)
    installation_id: UUID
    capability: Capability
    capability_version: int = Field(default=1, ge=1)
    rationale: str = Field(min_length=1, max_length=1024)
    user_id: UUID | None = None


class ClientIdentityIn(BaseModel):
    plugin_id: str = Field(min_length=1, max_length=128)
    installation_id: UUID
    device_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=128)


@router.get("/requests")
async def list_permission_requests(db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin)) -> list[dict]:
    del admin
    rows = await db.scalars(select(PluginPermissionRequest).order_by(PluginPermissionRequest.requested_at.desc()))
    return [
        {"id": str(row.id), "plugin_id": row.plugin_id, "installation_id": str(row.installation_id),
         "capability": row.capability, "capability_version": row.capability_version, "rationale": row.rationale,
         "user_id": str(row.user_id) if row.user_id else None, "status": row.status,
         "requested_at": row.requested_at, "resolved_at": row.resolved_at}
        for row in rows
    ]


@router.post("/requests", status_code=status.HTTP_201_CREATED)
async def create_permission_request(
    payload: PermissionRequestIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    if payload.user_id is not None and payload.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Cannot request permissions for another user.")
    row = PluginPermissionRequest(**payload.model_dump(), status="pending")
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": str(row.id), "status": row.status}


@router.post("/requests/{request_id}/deny")
async def deny_permission_request(
    request_id: UUID, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin)
) -> dict:
    row = await db.scalar(select(PluginPermissionRequest).where(PluginPermissionRequest.id == request_id))
    if row is None or row.status != "pending":
        raise HTTPException(status_code=404, detail="Pending permission request not found.")
    row.status = "denied"
    row.resolved_at = int(time.time())
    row.resolved_by = admin.id
    await db.commit()
    return {"id": str(row.id), "status": row.status}


@router.post("/requests/{request_id}/approve", status_code=status.HTTP_201_CREATED)
async def approve_permission_request(
    request_id: UUID, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin)
) -> dict:
    row = await db.scalar(select(PluginPermissionRequest).where(PluginPermissionRequest.id == request_id))
    if row is None or row.status != "pending":
        raise HTTPException(status_code=404, detail="Pending permission request not found.")
    grant = PluginPermissionGrant(
        plugin_id=row.plugin_id, installation_id=row.installation_id,
        capability=row.capability, capability_version=row.capability_version, user_id=row.user_id,
    )
    row.status = "approved"
    row.resolved_at = int(time.time())
    row.resolved_by = admin.id
    db.add(grant)
    await db.commit()
    return {"id": str(grant.id), "status": "granted"}


@router.get("/grants")
async def list_grants(db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin)) -> list[dict]:
    del admin
    rows = await db.scalars(select(PluginPermissionGrant).order_by(PluginPermissionGrant.granted_at.desc()))
    return [
        {"id": str(row.id), "plugin_id": row.plugin_id, "installation_id": str(row.installation_id),
         "capability": row.capability, "capability_version": row.capability_version,
         "user_id": str(row.user_id) if row.user_id else None, "device_id": str(row.device_id) if row.device_id else None,
         "granted_at": row.granted_at, "revoked_at": row.revoked_at, "active": row.revoked_at is None}
        for row in rows
    ]


@router.post("/grants/{grant_id}/revoke")
async def revoke_grant(grant_id: UUID, db: AsyncSession = Depends(get_db), admin: User = Depends(get_current_admin)) -> dict:
    del admin
    row = await db.scalar(select(PluginPermissionGrant).where(PluginPermissionGrant.id == grant_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Permission grant not found.")
    row.revoked_at = int(time.time())
    await db.commit()
    return {"id": str(row.id), "status": "revoked"}


@router.post("/clients", status_code=status.HTTP_201_CREATED)
async def create_client_identity(
    payload: ClientIdentityIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    issued = issue_client_credential(
        plugin_id=payload.plugin_id, installation_id=payload.installation_id, user_id=user.id,
        device_id=payload.device_id, name=payload.name,
    )
    row = PluginClientIdentity(
        id=issued.client.client_id, plugin_id=issued.client.plugin_id,
        installation_id=issued.client.installation_id, user_id=user.id, device_id=issued.client.device_id,
        name=issued.client.name, token_hash=hashlib.sha256(issued.token.encode()).hexdigest(),
    )
    db.add(row)
    await db.commit()
    return {"id": str(row.id), "plugin_id": row.plugin_id, "installation_id": str(row.installation_id),
            "device_id": str(row.device_id), "name": row.name, "credential": issued.token}


@router.get("/clients")
async def list_client_identities(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    rows = await db.scalars(
        select(PluginClientIdentity).where(PluginClientIdentity.user_id == user.id)
        .order_by(PluginClientIdentity.created_at.desc())
    )
    return [
        {"id": str(row.id), "plugin_id": row.plugin_id, "installation_id": str(row.installation_id),
         "device_id": str(row.device_id), "name": row.name, "created_at": row.created_at,
         "last_seen_at": row.last_seen_at, "revoked_at": row.revoked_at, "active": row.revoked_at is None}
        for row in rows
    ]


@router.post("/clients/{client_id}/revoke")
async def revoke_client_identity(client_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    row = await db.scalar(
        select(PluginClientIdentity).where(PluginClientIdentity.id == client_id, PluginClientIdentity.user_id == user.id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Client identity not found.")
    row.revoked_at = int(time.time())
    await db.commit()
    return {"id": str(row.id), "status": "revoked"}
