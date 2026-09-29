"""Tests for the stable Plugin API v1 wire contracts."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.plugin_api.contracts import (
    API_VERSION,
    Capability,
    ErrorCode,
    ErrorEnvelope,
    EventEnvelope,
    Page,
    Pagination,
    PluginIdentity,
    RequestContext,
    UserContext,
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
    assert identity.version == "1.2.3"

    with pytest.raises(ValidationError):
        PluginIdentity(
            plugin_id="Example Metadata",
            installation_id=uuid4(),
            version="1.2.3",
        )


def test_request_context_carries_only_scoped_identity() -> None:
    context = RequestContext(
        request_id=uuid4(),
        application_id=uuid4(),
        plugin=PluginIdentity(
            plugin_id="example.metadata",
            installation_id=uuid4(),
            version="1.0.0",
        ),
        user=UserContext(user_id=uuid4()),
        requested_capability=Capability.GAMES_READ,
    )
    assert context.requested_capability == Capability.GAMES_READ
    assert "database" not in context.model_dump_json().lower()
    assert "token" not in context.model_dump_json().lower()


def test_error_envelope_is_versioned_and_machine_readable() -> None:
    request_id = uuid4()
    error = ErrorEnvelope(
        code=ErrorCode.FORBIDDEN,
        message="Capability is not granted",
        request_id=request_id,
    )
    assert error.api_version == API_VERSION
    assert error.request_id == request_id
    assert error.code == ErrorCode.FORBIDDEN


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


def test_event_requires_versioned_utc_timestamp() -> None:
    event = EventEnvelope[dict[str, str]](
        event_id=uuid4(),
        event_type="game.updated",
        event_version=1,
        occurred_at=datetime(2026, 9, 29, 3, 0, tzinfo=timezone.utc),
        source="core",
        payload={"id": "game-1"},
    )
    assert event.api_version == API_VERSION
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
    from src.plugin_api.contracts import EventAck

    error = ErrorEnvelope(
        code=ErrorCode.INVALID_REQUEST,
        message="Invalid event payload",
        request_id=uuid4(),
    )
    ack = EventAck(event_id=uuid4(), accepted=False, error=error)
    assert not ack.accepted
    assert ack.error is not None
    assert ack.error.code == ErrorCode.INVALID_REQUEST


def test_provider_requests_are_normalized() -> None:
    notification = NotificationRequest(
        notification_id=uuid4(),
        user_id=uuid4(),
        title="Hello",
        body="World",
        created_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
    )
    result = NotificationResult(delivered=True, external_id="abc")
    metadata = MetadataProviderRequest(
        request_id=uuid4(),
        user_id=uuid4(),
        query="Example",
    )
    assert notification.title == "Hello"
    assert result.delivered
    assert metadata.query == "Example"
