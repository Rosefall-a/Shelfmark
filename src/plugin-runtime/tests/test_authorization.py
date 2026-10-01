"""Runtime authorization must fail closed without an affirmative host decision."""

from unittest.mock import Mock

import pytest
from runtime import PluginSpec, PluginSupervisor, RuntimePolicyError


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"payload": {}},
        {"payload": {"authorized": False}},
        {"payload": {"authorized": "true"}},
        {"payload": []},
    ],
)
def test_runtime_requires_affirmative_host_authorization(tmp_path, monkeypatch, response):
    supervisor = PluginSupervisor(root=tmp_path / "work", storage_root=tmp_path / "storage")
    monkeypatch.setattr(supervisor, "_handle_gateway_request", Mock(return_value=response))
    with pytest.raises(RuntimePolicyError, match="host did not authorize"):
        supervisor._authorize_capability("audit.plugin", "plugin.storage")


def test_storage_declaration_cannot_authorize_without_host(tmp_path):
    supervisor = PluginSupervisor(
        root=tmp_path / "work",
        storage_root=tmp_path / "storage",
        gateway_url="http://gateway",
        gateway_token="short",
    )
    supervisor._package_manifests["audit.plugin"] = {
        "permissions": [{"capability": {"name": "plugin.storage", "version": 1}}]
    }
    with pytest.raises(RuntimePolicyError, match="gateway is not configured"):
        supervisor._handle_gateway_request(
            "audit.plugin",
            {
                "method": "storage.put",
                "capability": "plugin.storage",
                "payload": {"key": "data", "value": "denied"},
            },
        )
    assert supervisor._storage("audit.plugin").get("data") is None


@pytest.mark.parametrize("existing_settings", [True, False])
def test_sandbox_does_not_expose_broker_storage_or_settings(
    tmp_path, monkeypatch, existing_settings
):
    monkeypatch.delenv("NONBUBBLE_ENV", raising=False)
    supervisor = PluginSupervisor(root=tmp_path / "work", storage_root=tmp_path / "storage")
    package = tmp_path / "package"
    package.mkdir()
    if existing_settings:
        (package / ".settings.json").write_text("{}", encoding="utf-8")
    command = supervisor._sandbox_command(
        PluginSpec("audit.plugin", ("python", "entry.py")), tmp_path / "workdir", package
    )
    assert str(supervisor._storage("audit.plugin").root) not in command
    index = command.index("/plugin-data")
    assert command[index - 1] == "--tmpfs"
    index = command.index("/plugin/.settings.json")
    assert command[index - 2 : index] == ["--ro-bind", "/dev/null"]
    assert (package / ".settings.json").is_file()
