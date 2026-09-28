# pylint: disable=duplicate-code
"""Admin API for deployment-wide provider credentials."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routes.settings import get_or_create_app_integration_settings
from src.core.auth import get_current_admin
from src.core.crypto import encrypt_secret
from src.core.provider_credentials import apply_deployment_provider_credentials
from src.database.models.user import User
from src.database.session import get_db

router = APIRouter(
    prefix="/api/settings/app-integrations/providers",
    tags=["settings"],
    dependencies=[Depends(get_current_admin)],
)


class DeploymentProviderCredentials(BaseModel):
    """Optional deployment-wide credentials; omitted fields are unchanged."""

    steamgriddb_api_key: str | None = None
    retroachievements_api_key: str | None = None
    giantbomb_api_key: str | None = None
    igdb_client_id: str | None = None
    igdb_client_secret: str | None = None
    screenscraper_ssid: str | None = None
    screenscraper_sspassword: str | None = None
    screenscraper_devid: str | None = None
    screenscraper_devpassword: str | None = None
    xbox_client_id: str | None = None
    xbox_client_secret: str | None = None


_SECRET_FIELDS = {
    "steamgriddb_api_key",
    "retroachievements_api_key",
    "giantbomb_api_key",
    "igdb_client_secret",
    "screenscraper_sspassword",
    "screenscraper_devpassword",
    "xbox_client_secret",
}
_SAFE_FIELDS = {
    "igdb_client_id",
    "screenscraper_ssid",
    "screenscraper_devid",
    "xbox_client_id",
}


@router.get("")
async def get_deployment_provider_credentials(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> dict[str, object]:
    """Return deployment credential status without exposing any secrets."""
    del admin
    row = await get_or_create_app_integration_settings(db)
    return {
        "configured": {
            field: bool(getattr(row, field)) for field in (*_SECRET_FIELDS, *_SAFE_FIELDS)
        },
        "fields": {field: getattr(row, field) for field in _SAFE_FIELDS if getattr(row, field)},
    }


@router.put("")
async def update_deployment_provider_credentials(
    payload: DeploymentProviderCredentials,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> dict[str, object]:
    """Save deployment-wide provider credentials, encrypting secrets at rest."""
    row = await get_or_create_app_integration_settings(db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        value = value.strip() if value else None
        setattr(row, field, encrypt_secret(value) if field in _SECRET_FIELDS and value else value)
    await db.commit()
    apply_deployment_provider_credentials(row)
    return await get_deployment_provider_credentials(db, admin=admin)


@router.delete("")
async def clear_deployment_provider_credentials(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> dict[str, object]:
    """Clear all deployment-wide provider credentials."""
    del admin
    row = await get_or_create_app_integration_settings(db)
    for field in (*_SECRET_FIELDS, *_SAFE_FIELDS):
        setattr(row, field, None)
    await db.commit()
    apply_deployment_provider_credentials(row)
    return {"configured": {}, "fields": {}}
