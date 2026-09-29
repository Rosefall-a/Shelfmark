"""Structured and redacted plugin runtime diagnostic coverage."""

from datetime import datetime

from runtime import PluginSupervisor


def test_diagnostics_are_structured_and_redact_sensitive_values(tmp_path) -> None:
    supervisor = PluginSupervisor(
        root=tmp_path / "work",
        storage_root=tmp_path / "storage",
    )

    supervisor._log(
        "example.plugin",
        "request failed token=super-secret https://hooks.example/api/webhooks/1/key",
        level="error",
        event="gateway.request_failed",
        correlation_id="request-1",
        metadata={"access_token": "also-secret", "attempt": 2},
    )

    event = supervisor.logs("example.plugin")[0]
    assert event["plugin_id"] == "example.plugin"
    assert event["level"] == "error"
    assert event["event"] == "gateway.request_failed"
    assert event["correlation_id"] == "request-1"
    assert event["metadata"] == {"access_token": "[REDACTED]", "attempt": 2}
    assert "super-secret" not in event["message"]
    assert "/webhooks/" not in event["message"]
    assert datetime.fromisoformat(event["timestamp"]).tzinfo is not None


def test_diagnostics_are_bounded_and_sequenced(tmp_path) -> None:
    supervisor = PluginSupervisor(
        root=tmp_path / "work",
        storage_root=tmp_path / "storage",
    )

    for index in range(205):
        supervisor._log("example.plugin", f"message {index}")

    events = supervisor.logs("example.plugin")
    assert len(events) == 200
    assert events[0]["sequence"] == 6
    assert events[-1]["sequence"] == 205
    assert events[-1]["message"] == "message 204"
