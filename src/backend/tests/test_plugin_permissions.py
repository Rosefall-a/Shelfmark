"""Tests for capability authorization and scoped client identities."""

from datetime import datetime, timezone
from uuid import uuid4

from src.plugin_api.contracts import (
    Capability,
    CapabilityRef,
    PluginIdentity,
    RequestContext,
    UserContext,
)
from src.plugin_api.permissions import (
    PermissionDecision,
    PermissionGrant,
    authorize_request,
    issue_client_credential,
)


def make_context(*, user_id=None, device_id=None):
    return RequestContext(
        request_id=uuid4(), application_id=uuid4(), gateway_id=uuid4(),
        plugin=PluginIdentity(plugin_id="example.plugin", installation_id=uuid4(), version="1.0.0"),
        user=UserContext(user_id=user_id, authenticated=True) if user_id else None,
        device_id=device_id,
        requested_capability=CapabilityRef(name=Capability.GAMES_READ, version=1),
    )


def make_grant(context, *, user_id=None, device_id=None, revoked_at=None):
    return PermissionGrant(
        plugin_id=context.plugin.plugin_id, installation_id=context.plugin.installation_id,
        capability=context.requested_capability, user_id=user_id, device_id=device_id,
        granted_at=datetime.now(timezone.utc), revoked_at=revoked_at,
    )


def test_default_deny():
    assert authorize_request(make_context(), ()).decision is PermissionDecision.DENIED


def test_matching_installation_capability_is_allowed():
    context = make_context(user_id=uuid4())
    assert authorize_request(context, (make_grant(context),)).decision is PermissionDecision.ALLOWED


def test_user_scope_is_enforced():
    context = make_context(user_id=uuid4())
    grant = make_grant(context, user_id=uuid4())
    assert authorize_request(context, (grant,)).decision is PermissionDecision.DENIED


def test_device_scope_is_enforced():
    context = make_context(user_id=uuid4(), device_id=uuid4())
    grant = make_grant(context, device_id=uuid4())
    assert authorize_request(context, (grant,)).decision is PermissionDecision.DENIED


def test_revocation_is_enforced():
    context = make_context()
    grant = make_grant(context, revoked_at=datetime.now(timezone.utc))
    assert authorize_request(context, (grant,)).decision is PermissionDecision.DENIED


def test_client_credential_is_high_entropy_and_bound_to_identity():
    user_id, installation_id, device_id = uuid4(), uuid4(), uuid4()
    issued = issue_client_credential(
        plugin_id="playnite.integration", installation_id=installation_id,
        user_id=user_id, device_id=device_id, name="Gaming PC",
    )
    assert issued.client.user_id == user_id
    assert issued.client.installation_id == installation_id
    assert issued.client.device_id == device_id
    assert issued.token.startswith("pmc1.")
    assert len(issued.token) > 64


def test_unauthenticated_context_is_denied_even_with_global_grant():
    context = make_context()
    grant = make_grant(context)
    context = context.model_copy(update={"user": None})
    assert authorize_request(context, (grant,)).decision is PermissionDecision.DENIED


def test_plugin_installation_mismatch_is_denied():
    context = make_context(user_id=uuid4())
    grant = make_grant(context)
    other = context.model_copy(
        update={"plugin": context.plugin.model_copy(update={"installation_id": uuid4()})}
    )
    assert authorize_request(other, (grant,)).decision is PermissionDecision.DENIED

def test_parent_grant_authorizes_children_but_leaf_grant_does_not_authorize_parent():
    context = make_context(user_id=uuid4())
    parent_grant = make_grant(context).model_copy(
        update={"capability": CapabilityRef(name=Capability.GAMES)}
    )
    assert authorize_request(context, (parent_grant,)).decision is PermissionDecision.ALLOWED

    parent_request = context.model_copy(
        update={"requested_capability": CapabilityRef(name=Capability.GAMES)}
    )
    leaf_grant = make_grant(context)
    assert authorize_request(parent_request, (leaf_grant,)).decision is PermissionDecision.DENIED


def test_same_plugin_id_does_not_transfer_grant_to_another_installation():
    context = make_context(user_id=uuid4())
    grant = make_grant(context)
    unrelated_installation = context.model_copy(
        update={
            "plugin": PluginIdentity(
                plugin_id=context.plugin.plugin_id,
                installation_id=uuid4(),
                version=context.plugin.version,
            )
        }
    )

    assert authorize_request(unrelated_installation, (grant,)).decision is PermissionDecision.DENIED
