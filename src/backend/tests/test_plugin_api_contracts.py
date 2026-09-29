"""Tests for the stable Plugin API v1 wire contracts."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.plugin_api.contracts import (
    API_VERSION,
    ApiVersion,
    Capability,
    CapabilityRef,
    ErrorCode,
    ErrorEnvelope,
    EventAck,
    EventEnvelope,
    GameRepresentation,
    MediaRepresentation,
    Page,
    Pagination,
    PluginIdentity,
    RequestContext,
    UserContext,
    UserRepresentation,
    VersionNegotiationRequest,
    VersionNegotiationResponse,
)
from src.plugin_api.coordinators import (
    MetadataCandidate,
    MetadataProviderRequest,
    NotificationRequest,
    NotificationResult,
)


def test_plugin_identity_is_stable_and_strict() -> None:
    identity = PluginIdentity(
        plugin_id="example.metadata",
        installation_id=uuid4(),
        version="1.2.3",
    )
    assert identity.plugin_id == "example.metadata"

    with pytest.raises(ValidationError):
        PluginIdentity(
            plugin_id="Example Metadata",
            installation_id=uuid4(),
            version="1.2.3",
        )


def test_request_context_contains_scoped_identity_and_capability_version() -> None:
    context = RequestContext(
        request_id=uuid4(),
        application_id=uuid4(),
        plugin=PluginIdentity(
            plugin_id="example.metadata",
            installation_id=uuid4(),
            version="1.0.0",
        ),
        user=UserContext(user_id=uuid4()),
        requested_capability=CapabilityRef(name=Capability.GAMES_READ, version=1),
    )
    wire = context.model_dump_json().lower()
    assert context.requested_capability.name == Capability.GAMES_READ
    assert "database" not in wire
    assert "token" not in wire


def test_core_representations_are_stable_and_non_orm() -> None:
    user = UserRepresentation(id=uuid4(), username="example")
    game = GameRepresentation(id=uuid4(), title="Example Game")
    media = MediaRepresentation(id=uuid4(), title="Example Media", media_type="movie")

    assert user.username == "example"
    assert game.title == "Example Game"
    assert media.media_type == "movie"

    with pytest.raises(ValidationError):
        GameRepresentation(id=uuid4(), title="Example", internal_model=object())


def test_error_envelope_is_versioned_and_machine_readable() -> None:
    error = ErrorEnvelope(
        code=ErrorCode.FORBIDDEN,
        message="Capability is not granted",
        request_id=uuid4(),
    )
    assert error.api_version == ApiVersion.V1


def test_pagination_has_bounded_limits() -> None:
    assert Pagination().limit == 50
    assert Pagination(limit=200).limit == 200

    with pytest.raises(ValidationError):
        Pagination(limit=201)


def test_page_contains_dtos_not_database_objects() -> None:
    page = Page[MetadataCandidate](
        items=(MetadataCandidate(
            external_id="123", title="Example", year=2026, provider="example"
        ),),
        next_cursor="next",
    )
    assert page.items[0].external_id == "123"
    assert page.next_cursor == "next"


def test_version_negotiation_is_explicit() -> None:
    request = VersionNegotiationRequest(supported_versions=(ApiVersion.V1,))
    response = VersionNegotiationResponse(selected_version=ApiVersion.V1)
    assert API_VERSION == "v1"
    assert request.supported_versions == (ApiVersion.V1,)
    assert not response.deprecated


def test_event_requires_versioned_utc_timestamp() -> None:
    event = EventEnvelope[dict[str, str]](
        event_id=uuid4(),
        event_type="game.updated",
        event_version=1,
        occurred_at=datetime(2026, 9, 29, 3, 0, tzinfo=timezone.utc),
        source="core",
        payload={"id": "game-1"},
    )
    assert event.api_version == ApiVersion.V1
    assert event.occurred_at.tzinfo == timezone.utc

    with pytest.raises(ValidationError):
        EventEnvelope[dict[str, str]](
            event_id=uuid4(),
            event_type="game.updated",
            event_version=1,
            occurred_at=datetime(2026, 9, 29, 3, 0),
            source="core",
            payload={"id": "game-1"},
        )


def test_event_acknowledges_failure_without_exception_details() -> None:
    error = ErrorEnvelope(
        code=ErrorCode.INVALID_REQUEST,
        message="Invalid event payload",
        request_id=uuid4(),
    )
    ack = EventAck(event_id=uuid4(), accepted=False, error=error)

    assert not ack.accepted
    assert ack.error is not None
    assert ack.error.code == ErrorCode.INVALID_REQUEST


def test_provider_requests_and_failures_are_normalized() -> None:
    notification = NotificationRequest(
        notification_id=uuid4(),
        user_id=uuid4(),
        title="Hello",
        body="World",
        created_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
    )
    delivered = NotificationResult(delivered=True, external_id="abc")
    failed = NotificationResult(delivered=False, detail="Provider unavailable")
    metadata = MetadataProviderRequest(
        request_id=uuid4(),
        user_id=uuid4(),
        query="Example",
    )

    assert notification.title == "Hello"
    assert delivered.delivered
    assert not failed.delivered
    assert metadata.query == "Example"
