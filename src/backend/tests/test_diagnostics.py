import pytest
from fastapi import HTTPException
from src.api.routes.health import health, health_diagnostics
from src.core import diagnostics

def test_health_is_minimal():
    assert health() == {"status": "ok"}

def test_environment_name(monkeypatch):
    monkeypatch.setattr(diagnostics.settings, "STARTUP_MODE", "dev")
    assert diagnostics.environment_name() == "development"
    monkeypatch.setattr(diagnostics.settings, "STARTUP_MODE", "testing")
    assert diagnostics.environment_name() == "testing"
    monkeypatch.setattr(diagnostics.settings, "STARTUP_MODE", "normal")
    assert diagnostics.environment_name() == "production-like"

def test_diagnostics_disabled_in_normal_mode(monkeypatch):
    monkeypatch.setattr(diagnostics.settings, "DEBUG", False)
    monkeypatch.setattr(diagnostics.settings, "STARTUP_MODE", "normal")
    assert not diagnostics.diagnostics_enabled()

@pytest.mark.asyncio
async def test_diagnostics_endpoint_is_hidden_when_disabled(monkeypatch):
    monkeypatch.setattr(diagnostics.settings, "DEBUG", False)
    monkeypatch.setattr(diagnostics.settings, "STARTUP_MODE", "normal")
    with pytest.raises(HTTPException) as exc:
        await health_diagnostics()
    assert exc.value.status_code == 404
