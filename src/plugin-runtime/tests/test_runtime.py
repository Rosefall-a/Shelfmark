from __future__ import annotations

import pytest

from runtime import (
    OutboundNetworkPolicy,
    PluginSpec,
    ResourceLimits,
    RuntimePolicyError,
)


def test_plugin_environment_is_default_deny_for_core_secrets() -> None:
    with pytest.raises(RuntimePolicyError):
        PluginSpec("example", ("run",), {"SECRET_KEY": "nope"}).validate()


def test_plugin_ids_and_commands_are_validated() -> None:
    with pytest.raises(RuntimePolicyError):
        PluginSpec("../escape", ("run",)).validate()
    with pytest.raises(RuntimePolicyError):
        PluginSpec("example", ()).validate()


def test_network_is_default_deny() -> None:
    policy = OutboundNetworkPolicy()
    policy.validate()
    assert policy.allowed_hosts == ()


def test_network_requires_capability_approval() -> None:
    with pytest.raises(RuntimePolicyError, match="network.outbound"):
        OutboundNetworkPolicy(("api.example.com",), (443,), False).validate()


def test_network_ports_are_bounded() -> None:
    with pytest.raises(RuntimePolicyError):
        OutboundNetworkPolicy(("api.example.com",), (70000,), True).validate()


def test_resource_limits_are_positive() -> None:
    with pytest.raises(RuntimePolicyError):
        PluginSpec(
            "example",
            ("run",),
            resources=ResourceLimits(cpu_seconds=0),
        ).validate()
