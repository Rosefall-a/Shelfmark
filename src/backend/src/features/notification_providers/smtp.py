from __future__ import annotations
import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.crypto import decrypt_secret
from src.core.env_handler import EnvConfigHandler
from src.database.models.app_integration_settings import AppIntegrationSettings
from src.database.models.notification_provider_setting import NotificationProviderSetting
from src.database.models.user import User
from src.features.notification_providers.base import DeliveryResult, NotificationMessage, ProviderDestination
logger=logging.getLogger(__name__)

@dataclass(frozen=True)
class SMTPConfig:
    enabled: bool
    host: str|None
    port: int
    username: str|None
    password: str|None
    from_email: str|None
    security: str

def _value(handler: EnvConfigHandler,row: AppIntegrationSettings,name:str,attr:str):
    if handler.has(name): return handler.get(name)
    value=getattr(row,attr)
    if name=="SMTP_PASSWORD" and value: return decrypt_secret(value)
    return value

async def load_smtp_config(db:AsyncSession)->SMTPConfig:
    from src.core.app_integrations import get_or_create_app_integration_settings
    row=await get_or_create_app_integration_settings(db); h=EnvConfigHandler()
    return SMTPConfig(bool(_value(h,row,"SMTP_ENABLED","smtp_enabled")),_value(h,row,"SMTP_HOST","smtp_host"),int(_value(h,row,"SMTP_PORT","smtp_port") or 587),_value(h,row,"SMTP_USERNAME","smtp_username"),_value(h,row,"SMTP_PASSWORD","smtp_password"),_value(h,row,"SMTP_FROM_EMAIL","smtp_from_email"),str(_value(h,row,"SMTP_SECURITY","smtp_security") or "starttls"))

def _valid_email(value:str)->bool:
    _,address=parseaddr(value)
    return "@" in address and "." in address.rsplit("@",1)[-1]

def _send(config:SMTPConfig,recipient:str,message:NotificationMessage)->None:
    if not config.host or not config.from_email or not _valid_email(config.from_email) or not _valid_email(recipient): raise ValueError("SMTP provider is not fully configured or the user email is invalid.")
    mail=EmailMessage(); mail["Subject"]=message.title; mail["From"]=config.from_email; mail["To"]=recipient; mail.set_content(f"{message.body}\n\n{message.title}")
    context=ssl.create_default_context()
    if config.security=="ssl":
        with smtplib.SMTP_SSL(config.host,config.port,timeout=10,context=context) as smtp:
            if config.username and config.password: smtp.login(config.username,config.password)
            smtp.send_message(mail)
    else:
        with smtplib.SMTP(config.host,config.port,timeout=10) as smtp:
            smtp.ehlo()
            if config.security=="starttls": smtp.starttls(context=context); smtp.ehlo()
            if config.username and config.password: smtp.login(config.username,config.password)
            smtp.send_message(mail)

class SMTPNotificationProvider:
    id="smtp"; name="Email (SMTP)"
    def available(self) -> bool:
        return bool(
            self.config.enabled
            and self.config.host
            and self.config.from_email
            and self.config.security in {"none", "starttls", "ssl"}
            and 1 <= self.config.port <= 65535
        )
    def __init__(self,config:SMTPConfig): self.config=config
    async def lookup_destination(self,db,user,setting):
        del db,setting
        if not self.available() or not _valid_email((user.email or "").strip()): return None
        return ProviderDestination(user.email.strip(),user.email.strip())
    def enabled_for_user(self,setting): return setting is None or setting.enabled
    async def deliver(self,destination,message):
        try: await asyncio.to_thread(_send,self.config,destination.value,message)
        except (OSError,smtplib.SMTPException,TimeoutError,ValueError):
            logger.warning("SMTP notification delivery failed")
            return DeliveryResult(False,"SMTP delivery failed.")
        except Exception:
            logger.exception("Unexpected SMTP notification delivery failure"); return DeliveryResult(False,"SMTP delivery failed.")
        return DeliveryResult(True)

async def smtp_provider(db:AsyncSession)->SMTPNotificationProvider:
    try:
        return SMTPNotificationProvider(await load_smtp_config(db))
    except Exception:
        logger.warning("SMTP notification configuration could not be loaded")
        return SMTPNotificationProvider(SMTPConfig(False, None, 587, None, None, None, "starttls"))
