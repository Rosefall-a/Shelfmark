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
    DocumentContentRepresentation,
    DocumentRepresentation,
    ErrorCode,
    ErrorEnvelope,
    EventAck,
    EventEnvelope,
    GameRepresentation,
    MediaRepresentation,
    NotificationDeliveryRepresentation,
    NotificationDeliveryResult,
    NotificationProviderRegistration,
    Page,
    Pagination,
    PluginIdentity,
    RequestContext,
    SessionRepresentation,
    UserContext,
    UserRepresentation,
    VersionNegotiationRequest,
    VersionNegotiationResponse,
    CompatibilityStatus,
    DependencyResolutionError,
    PluginManifest,
    PluginDependency,
    PermissionDeclaration,
    evaluate_manifest_compatibility,
    migrate_manifest_data,
    resolve_plugin_dependencies,
    version_satisfies,
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
        gateway_id=uuid4(),
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


def test_domain_capability_contracts_exclude_sensitive_host_state() -> None:
    document = DocumentRepresentation(
        id=uuid4(),
        game_id=uuid4(),
        game_title="Example",
        filename="manual.pdf",
        media_type="application/pdf",
        size_bytes=100,
        created_at=1,
    )
    content = DocumentContentRepresentation(
        document=document,
        encoding="base64",
        content="cGRm",
    )
    session = SessionRepresentation(id=uuid4(), created_at=1, expires_at=2, active=True)
    provider = NotificationProviderRegistration(
        provider_id="example.plugin.webhook",
        name="Webhook",
        action_id="deliver",
    )
    delivery = NotificationDeliveryRepresentation(
        notification_id=uuid4(),
        kind="plugin",
        title="Title",
        body="Body",
        media_type="plugin",
        media_id=uuid4(),
        event_at=1,
    )
    result = NotificationDeliveryResult(success=False, retryable=True, error="later")

    wire = " ".join(
        value.model_dump_json() for value in (content, session, provider, delivery, result)
    ).lower()
    assert "token_hash" not in wire
    assert "filesystem" not in wire
    assert "database" not in wire
    assert "secret" not in wire
    assert Capability.DOCUMENTS_READ.value == "documents.read"
    assert Capability.SESSIONS_REVOKE.value == "sessions.revoke"
    assert Capability.NOTIFICATION_PROVIDERS_DELIVER.value == "notification_providers.deliver"


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
        items=(
            MetadataCandidate(external_id="123", title="Example", year=2026, provider="example"),
        ),
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


def manifest_data(
    *,
    plugin_id: str = "example.metadata",
    version: str = "1.2.3",
    sdk_range: str = ">=1.0.0,<2.0.0",
    app_range: str = ">=1.0.0,<3.0.0",
    dependencies: tuple[PluginDependency, ...] = (),
) -> dict:
    return {
        "plugin_id": plugin_id,
        "name": "Example Metadata",
        "version": version,
        "entrypoint": "plugin:main",
        "sdk_version_range": sdk_range,
        "application_version_range": app_range,
        "dependencies": dependencies,
        "capabilities": (CapabilityRef(name=Capability.MEDIA_READ),),
        "permissions": (
            PermissionDeclaration(
                capability=CapabilityRef(name=Capability.MEDIA_READ),
                rationale="Read media for metadata enrichment",
            ),
        ),
        "integrity": {"sha256": "a" * 64},
    }


def test_manifest_is_static_and_rejects_unsafe_or_ambiguous_fields() -> None:
    manifest = PluginManifest.model_validate(manifest_data())
    assert manifest.plugin_id == "example.metadata"
    assert manifest.entrypoint == "plugin:main"

    with pytest.raises(ValidationError):
        PluginManifest.model_validate({**manifest_data(), "entrypoint": "../plugin:main"})
    with pytest.raises(ValidationError):
        PluginManifest.model_validate({**manifest_data(), "plugin_id": "Example Plugin"})
    with pytest.raises(ValidationError):
        PluginManifest.model_validate({**manifest_data(), "unexpected": "value"})


def test_manifest_compatibility_is_evaluated_without_execution() -> None:
    manifest = PluginManifest.model_validate(manifest_data())
    compatible = evaluate_manifest_compatibility(manifest, "1.5.0", "2.1.0")
    incompatible = evaluate_manifest_compatibility(manifest, "2.0.0", "2.1.0")

    assert compatible.status == CompatibilityStatus.COMPATIBLE
    assert compatible.action == "allow"
    assert incompatible.status == CompatibilityStatus.INCOMPATIBLE
    assert incompatible.action == "quarantine"


def test_semver_ranges_are_deterministic() -> None:
    assert version_satisfies("1.5.0", ">=1.0.0,<2.0.0")
    assert version_satisfies("1.5.0", "^1.2.0")
    assert version_satisfies("1.2.9", "~1.2.0")
    assert version_satisfies("1.5.0", "1.x")
    assert not version_satisfies("2.0.0", "^1.2.0")


def test_manifest_migration_is_pure_and_rejects_ambiguous_data() -> None:
    migrated = migrate_manifest_data(
        {
            "id": "example.metadata",
            "display_name": "Example",
            "version": "1.2.3",
            "entry_point": "plugin:main",
            "sdk_version": "1.0.0",
            "app_version": "2.0.0",
            "integrity": {"sha256": "a" * 64},
        }
    )
    assert migrated["manifest_version"] == 1
    assert migrated["plugin_id"] == "example.metadata"
    assert migrated["sdk_version_range"] == "=1.0.0"

    with pytest.raises(ValueError):
        migrate_manifest_data({"id": "a", "plugin_id": "b"})


def test_dependency_resolution_is_dependency_first_and_detects_cycles() -> None:
    base = PluginManifest.model_validate(manifest_data(plugin_id="base"))
    dependent = PluginManifest.model_validate(
        manifest_data(
            plugin_id="dependent",
            dependencies=(PluginDependency(plugin_id="base", version_range="^1.0.0"),),
        ),
    )
    assert resolve_plugin_dependencies((dependent, base)) == ("base", "dependent")

    bad = PluginManifest.model_validate(
        manifest_data(
            plugin_id="missing-dependent",
            dependencies=(PluginDependency(plugin_id="missing", version_range="^1.0.0"),),
        ),
    )
    with pytest.raises(DependencyResolutionError):
        resolve_plugin_dependencies((bad,))

    first = PluginManifest.model_validate(
        manifest_data(
            plugin_id="first",
            dependencies=(PluginDependency(plugin_id="second", version_range="^1.0.0"),),
        ),
    )
    second = PluginManifest.model_validate(
        manifest_data(
            plugin_id="second",
            dependencies=(PluginDependency(plugin_id="first", version_range="^1.0.0"),),
        ),
    )
    with pytest.raises(DependencyResolutionError, match="dependency cycle"):
        resolve_plugin_dependencies((first, second))


def test_manifest_permissions_must_match_declared_capabilities() -> None:
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(
            {
                **manifest_data(),
                "capabilities": (CapabilityRef(name=Capability.GAMES_READ),),
            }
        )
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(
            {
                **manifest_data(),
                "capabilities": (CapabilityRef(name=Capability.MEDIA_READ, version=2),),
            }
        )
