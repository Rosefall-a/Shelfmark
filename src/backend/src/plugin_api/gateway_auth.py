"""Application-to-plugin-gateway bootstrap authentication primitives.

The gateway trust boundary is based on explicit identities and high-entropy
credentials, never on a configured URL or network location. Credential
material is stored only as keyed digests by the injected credential store.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import hashlib
import hmac
import secrets
from collections.abc import Callable
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import Field

from .contracts import ApiVersion, ContractModel


class CredentialError(ValueError):
    """Raised when a gateway credential cannot be authenticated."""


class ReplayError(CredentialError):
    """Raised when a bootstrap nonce is replayed."""


class CredentialKind(StrEnum):
    """Credential classes with deliberately different trust purposes."""

    BOOTSTRAP = "bootstrap"
    SESSION = "session"


class ApplicationIdentity(ContractModel):
    """Stable identity of the core application instance."""

    application_id: UUID = Field(default_factory=uuid4)


class GatewayIdentity(ContractModel):
    """Stable identity of one plugin gateway instance."""

    gateway_id: UUID = Field(default_factory=uuid4)


class BootstrapRequest(ContractModel):
    """Authenticated core-to-gateway bootstrap request."""

    application_id: UUID
    gateway_id: UUID
    nonce: UUID = Field(default_factory=uuid4)
    issued_at: datetime
    credential: str = Field(min_length=32, max_length=512)
    supported_versions: tuple[ApiVersion, ...] = Field(min_length=1)


class GatewayHandshake(ContractModel):
    """Gateway response establishing a short-lived authenticated session."""

    application_id: UUID
    gateway_id: UUID
    selected_version: ApiVersion
    credential: str = Field(min_length=32, max_length=512)
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CredentialRecord:
    """Server-side metadata; raw credential secrets are never retained."""

    credential_id: UUID
    kind: CredentialKind
    subject_id: UUID
    digest: bytes
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None


class CredentialStore(Protocol):
    """Persistence boundary for credential metadata and replay state."""

    def save(self, record: CredentialRecord) -> None:
        """Persist a credential record."""

    def get(self, credential_id: UUID) -> CredentialRecord | None:
        """Retrieve a credential record by public credential ID."""

    def revoke(self, credential_id: UUID, revoked_at: datetime) -> None:
        """Revoke one credential."""

    def mark_nonce_used(self, nonce: UUID, expires_at: datetime) -> bool:
        """Atomically record a bootstrap nonce; false means it was already used."""


class InMemoryCredentialStore:
    """Reference store for tests/development; not durable across restarts."""

    def __init__(self) -> None:
        self._credentials: dict[UUID, CredentialRecord] = {}
        self._used_nonces: dict[UUID, datetime] = {}

    def save(self, record: CredentialRecord) -> None:
        self._credentials[record.credential_id] = record

    def get(self, credential_id: UUID) -> CredentialRecord | None:
        return self._credentials.get(credential_id)

    def revoke(self, credential_id: UUID, revoked_at: datetime) -> None:
        record = self._credentials.get(credential_id)
        if record is None:
            return
        self._credentials[credential_id] = CredentialRecord(
            credential_id=record.credential_id, kind=record.kind, subject_id=record.subject_id,
            digest=record.digest, issued_at=record.issued_at, expires_at=record.expires_at,
            revoked_at=revoked_at,
        )

    def mark_nonce_used(self, nonce: UUID, expires_at: datetime) -> bool:
        if nonce in self._used_nonces and self._used_nonces[nonce] > expires_at - timedelta(minutes=10):
            return False
        self._used_nonces[nonce] = expires_at
        return True


class GatewayAuthenticator:
    """Authenticate the core application to one explicitly identified gateway."""

    def __init__(
        self, application: ApplicationIdentity, gateway: GatewayIdentity, *,
        store: CredentialStore | None = None, secret: bytes,
        clock: Callable[[], datetime] | None = None,
        clock_skew: timedelta = timedelta(seconds=30),
        bootstrap_ttl: timedelta = timedelta(minutes=10),
        session_ttl: timedelta = timedelta(minutes=5),
    ) -> None:
        if len(secret) < 32:
            raise ValueError("credential secret must contain at least 256 bits")
        if clock_skew < timedelta(0):
            raise ValueError("clock skew must not be negative")
        if bootstrap_ttl <= timedelta(0) or session_ttl <= timedelta(0):
            raise ValueError("credential lifetimes must be positive")
        self.application = application
        self.gateway = gateway
        self._store = store or InMemoryCredentialStore()
        self._secret = secret
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._clock_skew = clock_skew
        self._bootstrap_ttl = bootstrap_ttl
        self._session_ttl = session_ttl

    @staticmethod
    def generate_secret() -> bytes:
        """Generate 256 bits of bootstrap/keying material."""
        return secrets.token_bytes(32)

    def _digest(self, credential_secret: str) -> bytes:
        return hmac.new(self._secret, credential_secret.encode("ascii"), hashlib.sha256).digest()

    def _issue(self, *, kind: CredentialKind, subject_id: UUID, ttl: timedelta, now: datetime) -> str:
        credential_id = uuid4()
        credential_secret = secrets.token_urlsafe(48)
        self._store.save(CredentialRecord(
            credential_id=credential_id, kind=kind, subject_id=subject_id,
            digest=self._digest(credential_secret), issued_at=now, expires_at=now + ttl,
        ))
        return f"pm1.{kind.value}.{credential_id}.{credential_secret}"

    def issue_bootstrap_credential(self, *, now: datetime | None = None) -> str:
        """Issue a bounded bootstrap credential for this application."""
        current = now or self._clock()
        return self._issue(kind=CredentialKind.BOOTSTRAP, subject_id=self.application.application_id,
                           ttl=self._bootstrap_ttl, now=current)

    def _parse(self, token: str) -> tuple[CredentialKind, UUID, str]:
        parts = token.split(".")
        if len(parts) != 4 or parts[0] != "pm1":
            raise CredentialError("invalid gateway credential")
        try:
            kind = CredentialKind(parts[1])
            credential_id = UUID(parts[2])
        except (ValueError, IndexError) as exc:
            raise CredentialError("invalid gateway credential") from exc
        if len(parts[3]) < 32:
            raise CredentialError("invalid gateway credential")
        return kind, credential_id, parts[3]

    def _authenticate(self, token: str, *, kind: CredentialKind, subject_id: UUID, now: datetime) -> CredentialRecord:
        parsed_kind, credential_id, credential_secret = self._parse(token)
        if parsed_kind is not kind:
            raise CredentialError("credential kind is not valid for this operation")
        record = self._store.get(credential_id)
        if record is None or record.subject_id != subject_id:
            raise CredentialError("credential is not recognized")
        if record.revoked_at is not None:
            raise CredentialError("credential has been revoked")
        if now > record.expires_at:
            raise CredentialError("credential has expired")
        if not hmac.compare_digest(record.digest, self._digest(credential_secret)):
            raise CredentialError("credential is not recognized")
        return record

    def bootstrap(self, request: BootstrapRequest) -> GatewayHandshake:
        """Validate bootstrap trust, replay protection and API compatibility."""
        now = self._clock()
        if request.application_id != self.application.application_id:
            raise CredentialError("application identity does not match gateway configuration")
        if request.gateway_id != self.gateway.gateway_id:
            raise CredentialError("gateway identity does not match gateway configuration")
        if abs((now - request.issued_at).total_seconds()) > self._clock_skew.total_seconds():
            raise CredentialError("bootstrap request timestamp is outside the allowed skew")
        self._authenticate(request.credential, kind=CredentialKind.BOOTSTRAP,
                           subject_id=self.application.application_id, now=now)
        if not self._store.mark_nonce_used(request.nonce, now + self._bootstrap_ttl):
            raise ReplayError("bootstrap nonce has already been used")
        if ApiVersion.V1 not in request.supported_versions:
            raise CredentialError("no compatible Plugin API version")
        credential = self._issue(kind=CredentialKind.SESSION, subject_id=self.application.application_id,
                                 ttl=self._session_ttl, now=now)
        return GatewayHandshake(application_id=self.application.application_id, gateway_id=self.gateway.gateway_id,
                                selected_version=ApiVersion.V1, credential=credential,
                                issued_at=now, expires_at=now + self._session_ttl)

    def authenticate_session(self, token: str, *, now: datetime | None = None) -> GatewayHandshake:
        """Validate a core session credential and return its authenticated identities."""
        current = now or self._clock()
        record = self._authenticate(token, kind=CredentialKind.SESSION,
                                    subject_id=self.application.application_id, now=current)
        return GatewayHandshake(application_id=self.application.application_id, gateway_id=self.gateway.gateway_id,
                                selected_version=ApiVersion.V1, credential=token,
                                issued_at=record.issued_at, expires_at=record.expires_at)

    def rotate_credential(self, token: str, *, kind: CredentialKind, now: datetime | None = None) -> str:
        """Revoke a valid credential and issue a replacement for the same application."""
        current = now or self._clock()
        record = self._authenticate(token, kind=kind, subject_id=self.application.application_id, now=current)
        self._store.revoke(record.credential_id, current)
        ttl = self._bootstrap_ttl if kind is CredentialKind.BOOTSTRAP else self._session_ttl
        return self._issue(kind=kind, subject_id=record.subject_id, ttl=ttl, now=current)

    def revoke_credential(self, token: str, *, kind: CredentialKind, now: datetime | None = None) -> None:
        """Revoke a valid credential after verifying its kind and application binding."""
        current = now or self._clock()
        record = self._authenticate(token, kind=kind, subject_id=self.application.application_id, now=current)
        self._store.revoke(record.credential_id, current)


__all__ = [
    "ApplicationIdentity", "BootstrapRequest", "CredentialError", "CredentialKind",
    "CredentialRecord", "CredentialStore", "GatewayAuthenticator", "GatewayHandshake",
    "GatewayIdentity", "InMemoryCredentialStore", "ReplayError",
]