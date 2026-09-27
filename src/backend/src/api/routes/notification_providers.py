from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.auth import get_current_user
from src.core.crypto import encrypt_secret
from src.database.models.notification_provider_setting import NotificationProviderSetting
from src.database.models.user import User
from src.database.session import get_db
from src.features.notification_providers.registry import PROVIDER_IDS,get_notification_providers
from src.features.notification_providers.discord import validate_webhook_url

router=APIRouter(prefix="/api/settings/notification-providers",tags=["settings"],dependencies=[Depends(get_current_user)])

class ProviderUpdate(BaseModel):
    enabled: bool|None=None
    destination: str|None=None

async def _setting(db,user_id:UUID,provider_id:str):
    row=await db.scalar(select(NotificationProviderSetting).where(NotificationProviderSetting.user_id==user_id,NotificationProviderSetting.provider_id==provider_id))
    if row is None:
        row=NotificationProviderSetting(user_id=user_id,provider_id=provider_id,enabled=True)
        db.add(row); await db.flush()
    return row

@router.get("")
async def get_notification_provider_settings(db:AsyncSession=Depends(get_db),current_user:User=Depends(get_current_user)):
    providers=await get_notification_providers(db)
    result=[]
    for provider_id in PROVIDER_IDS:
        row=await _setting(db,current_user.id,provider_id)
        result.append({"id":provider_id,"name":providers[provider_id].name,"enabled":bool(row.enabled),"available":providers[provider_id].available(),"configured":bool(row.destination_secret) if provider_id=="discord" else providers[provider_id].available(),"destination":None if provider_id=="discord" else current_user.email})
    await db.commit()
    return result

@router.put("/{provider_id}")
async def update_notification_provider(provider_id:str,payload:ProviderUpdate,db:AsyncSession=Depends(get_db),current_user:User=Depends(get_current_user)):
    if provider_id not in PROVIDER_IDS: raise HTTPException(404,"Unknown notification provider.")
    row=await _setting(db,current_user.id,provider_id)
    if payload.enabled is not None: row.enabled=payload.enabled
    if provider_id=="discord" and payload.destination is not None:
        value=payload.destination.strip()
        if value and not validate_webhook_url(value): raise HTTPException(422,"Enter a valid Discord webhook URL.")
        row.destination_secret=encrypt_secret(value) if value else None
    elif payload.destination is not None:
        raise HTTPException(400,"This provider does not accept a user destination.")
    await db.commit()
    providers=await get_notification_providers(db)
    return {"id":provider_id,"enabled":row.enabled,"available":providers[provider_id].available(),"configured":bool(row.destination_secret) if provider_id=="discord" else providers[provider_id].available()}

@router.delete("/{provider_id}/destination",status_code=204)
async def revoke_notification_provider_destination(provider_id:str,db:AsyncSession=Depends(get_db),current_user:User=Depends(get_current_user)):
    if provider_id!="discord": raise HTTPException(400,"This provider has no revocable destination.")
    row=await _setting(db,current_user.id,provider_id); row.destination_secret=None; row.enabled=False; await db.commit()
