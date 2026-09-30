"""OpenID Connect helpers."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request
from starlette.responses import RedirectResponse

from src.core.config import settings

oauth = OAuth()


@dataclass(frozen=True)
class OidcConfig:
    issuer_url: str
    client_id: str
    client_secret: str
    scopes: str = "openid profile email"
    redirect_uri: str | None = None
    groups_claim: str = "groups"
    admin_group: str | None = None
    user_match_field: str = "email"
    allow_new_users: bool = True
    discovery_url: str | None = None
    name: str = "SSO"
    slug: str = "default"
    button_text: str = "Continue with SSO"
    button_image_url: str | None = None

    @property
    def server_metadata_url(self) -> str:
        configured = (self.discovery_url or self.issuer_url).strip().rstrip("/")
        suffix = "/.well-known/openid-configuration"
        if configured.endswith(suffix):
            return configured
        return urljoin(configured + "/", ".well-known/openid-configuration")


def env_oidc_config() -> OidcConfig | None:
    if not (settings.OIDC_ISSUER_URL and settings.OIDC_CLIENT_ID and settings.OIDC_CLIENT_SECRET):
        return None
    issuer = settings.OIDC_ISSUER_URL.strip()
    return OidcConfig(
        issuer_url=issuer,
        client_id=settings.OIDC_CLIENT_ID,
        client_secret=settings.OIDC_CLIENT_SECRET,
        scopes=settings.OIDC_SCOPES,
        redirect_uri=settings.OIDC_REDIRECT_URI,
        groups_claim=settings.OIDC_GROUPS_CLAIM,
        admin_group=settings.OIDC_ADMIN_GROUP,
        user_match_field=getattr(settings, "OIDC_USER_MATCH_FIELD", "email"),
        discovery_url=issuer if issuer.endswith("/.well-known/openid-configuration") else None,
    )


def register_oidc_provider(config: OidcConfig, client_name: str = "oidc") -> None:
    oauth.register(
        name=client_name,
        client_id=config.client_id,
        client_secret=config.client_secret,
        server_metadata_url=config.server_metadata_url,
        client_kwargs={"scope": config.scopes},
        overwrite=True,
    )


def callback_url(request: Request, config: OidcConfig) -> str:
    if config.redirect_uri:
        configured = config.redirect_uri.strip()
        # A provider migrated from the old single-provider configuration may
        # still contain the legacy callback path. Named providers have their
        # own callback route, so transparently upgrade that old path while
        # preserving the configured scheme/host/port.
        if config.slug != "default":
            parts = urlsplit(configured)
            if parts.path.rstrip("/") == "/api/auth/oidc/callback":
                parts = parts._replace(path=f"/api/auth/oidc/callback/{config.slug}")
                return urlunsplit(parts)
        return configured
    return (
        str(request.url_for("oidc_callback_provider", provider_slug=config.slug))
        if config.slug != "default"
        else str(request.url_for("oidc_callback"))
    )


async def begin_oidc(request: Request, config: OidcConfig) -> RedirectResponse:
    client_name = f"oidc_{config.slug}" if config.slug != "default" else "oidc"
    register_oidc_provider(config, client_name)
    client = oauth.create_client(client_name)
    if client is None:
        raise HTTPException(status_code=503, detail="OIDC provider is unavailable.")
    return await client.authorize_redirect(request, callback_url(request, config))
