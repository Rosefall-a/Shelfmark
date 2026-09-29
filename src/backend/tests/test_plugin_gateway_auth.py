"""Security regression tests for application-to-gateway bootstrap authentication."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.plugin_api.contracts import ApiVersion
from src.plugin_api.gateway_auth import (
    ApplicationIdentity, BootstrapRequest, CredentialError, CredentialKind,
    GatewayAuthenticator, GatewayIdentity, InMemoryCredentialStore, ReplayError,
)


def make_auth(now: datetime | None = None) -> tuple[GatewayAuthenticator, datetime]:
    current = now or datetime(2026, 9, 29, 3, 0, tzinfo=timezone.utc)
    return GatewayAuthenticator(ApplicationIdentity(), GatewayIdentity(), store=InMemoryCredentialStore(),
                                secret=b"x" * 32, clock=lambda: current), current


def request_for(auth: GatewayAuthenticator, credential: str, now: datetime, nonce=None) -> BootstrapRequest:
    return BootstrapRequest(application_id=auth.application.application_id, gateway_id=auth.gateway.gateway_id,
                            nonce=nonce or uuid4(), issued_at=now, credential=credential,
                            supported_versions=(ApiVersion.V1,))


def test_bootstrap_binds_application_and_gateway_identity() -> None:
    auth, now = make_auth()
    response = auth.bootstrap(request_for(auth, auth.issue_bootstrap_credential(now=now), now))
    assert response.application_id == auth.application.application_id
    assert response.gateway_id == auth.gateway.gateway_id
    assert response.selected_version is ApiVersion.V1


def test_bootstrap_rejects_wrong_identity_and_replay() -> None:
    auth, now = make_auth()
    credential = auth.issue_bootstrap_credential(now=now)
    wrong_identity = request_for(auth, credential, now).model_copy(update={"application_id": uuid4()})
    with pytest.raises(CredentialError):
        auth.bootstrap(wrong_identity)
    valid = request_for(auth, credential, now)
    auth.bootstrap(valid)
    with pytest.raises(ReplayError):
        auth.bootstrap(valid)


def test_bootstrap_rejects_stale_timestamp() -> None:
    auth, now = make_auth()
    credential = auth.issue_bootstrap_credential(now=now)
    stale = request_for(auth, credential, now - timedelta(minutes=1))
    with pytest.raises(CredentialError):
        auth.bootstrap(stale)


def test_bootstrap_rejects_unsupported_version() -> None:
    auth, now = make_auth()
    credential = auth.issue_bootstrap_credential(now=now)
    request = request_for(auth, credential, now).model_dump()
    request["supported_versions"] = ()
    with pytest.raises(ValueError):
        BootstrapRequest.model_validate(request)


def test_session_is_short_lived_and_revocable() -> None:
    auth, now = make_auth()
    response = auth.bootstrap(request_for(auth, auth.issue_bootstrap_credential(now=now), now))
    assert auth.authenticate_session(response.credential, now=now).credential == response.credential
    auth.revoke_credential(response.credential, kind=CredentialKind.SESSION, now=now)
    with pytest.raises(CredentialError):
        auth.authenticate_session(response.credential, now=now)


def test_rotation_revokes_old_credential() -> None:
    auth, now = make_auth()
    old = auth.issue_bootstrap_credential(now=now)
    new = auth.rotate_credential(old, kind=CredentialKind.BOOTSTRAP, now=now)
    assert new != old
    with pytest.raises(CredentialError):
        auth.rotate_credential(old, kind=CredentialKind.BOOTSTRAP, now=now)
    assert new.startswith("pm1.bootstrap.")
