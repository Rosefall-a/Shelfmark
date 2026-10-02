"""Subscriptions use authenticated action identity and target-user live grants."""

from uuid import uuid4

import pytest
from runtime import PluginSupervisor, RuntimePolicyError


@pytest.fixture
def supervisor(tmp_path, monkeypatch):
    instance = PluginSupervisor(tmp_path / "workers", tmp_path / "storage")
    instance._user_ids["test.plugin"] = str(uuid4())
    monkeypatch.setattr(instance, "_authorize_capability", lambda *args, **kwargs: None)
    return instance


def dispatch(supervisor, method, payload=None, user=None):
    return supervisor._handle_gateway_request(
        "test.plugin",
        {
            "method": method,
            "capability": "tasks.background",
            "payload": payload or {},
            "request_id": str(uuid4()),
        },
        user_id=user,
    )["payload"]


def test_opt_in_is_bound_to_action_user_and_persists(supervisor):
    user = str(uuid4())
    with pytest.raises(RuntimePolicyError, match="authenticated"):
        dispatch(supervisor, "tasks.subscribe")
    dispatch(supervisor, "tasks.subscribe", user=user)
    assert dispatch(supervisor, "tasks.subscribers")["users"] == [user]
    dispatch(supervisor, "tasks.unsubscribe", user=user)
    assert dispatch(supervisor, "tasks.subscribers")["users"] == []


def test_reserved_namespace_and_unsubscribed_target_cannot_be_forged(supervisor):
    with pytest.raises(RuntimePolicyError, match="reserved"):
        dispatch(
            supervisor,
            "storage.put",
            {"key": "host/tasks/" + str(uuid4()), "value": "forged"},
        )
    with pytest.raises(RuntimePolicyError, match="not subscribed"):
        dispatch(
            supervisor,
            "tasks.request",
            {
                "user_id": str(uuid4()),
                "method": "media.sync",
                "capability": "media.write",
            },
        )


def test_subscription_does_not_allow_arbitrary_operations_and_checks_target_grant(
    supervisor, monkeypatch
):
    user = str(uuid4())
    dispatch(supervisor, "tasks.subscribe", user=user)
    with pytest.raises(RuntimePolicyError, match="unsupported"):
        dispatch(
            supervisor,
            "tasks.request",
            {
                "user_id": user,
                "method": "sessions.revoke",
                "capability": "sessions.revoke",
            },
        )

    def authorize(*args, **kwargs):
        if kwargs["user_id"] == user:
            raise RuntimePolicyError("target grant revoked")

    monkeypatch.setattr(supervisor, "_authorize_capability", authorize)
    with pytest.raises(RuntimePolicyError, match="revoked"):
        dispatch(
            supervisor,
            "tasks.request",
            {"user_id": user, "method": "media.sync", "capability": "media.write"},
        )
