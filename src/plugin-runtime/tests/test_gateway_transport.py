"""The private HTTP bridge preserves the public v1 JSON-line contract."""

import io
import json
from urllib.error import HTTPError
from uuid import uuid4

import pytest
from runtime import (
    PluginSupervisor,
    RuntimeGatewayError,
    RuntimePolicyError,
    gateway_error_response,
)


@pytest.fixture
def supervisor(tmp_path):
    instance = PluginSupervisor(
        tmp_path / "workers",
        tmp_path / "storage",
        gateway_url="http://replaceable-transport.example",
        gateway_token="x" * 32,
    )
    instance._installation_ids["contract"] = str(uuid4())
    instance._user_ids["contract"] = str(uuid4())
    return instance


def test_gateway_preserves_supplied_correlation_and_accepts_legacy_response(
    supervisor, monkeypatch
):
    request_id = str(uuid4())

    def transport(request, *, timeout):
        assert timeout == 10
        body = json.loads(request.data)
        assert body["api_version"] == "v1" and body["request_id"] == request_id
        assert body["installation_id"] == supervisor._installation_ids["contract"]
        return io.BytesIO(b'{"payload":{"authorized":true}}')

    monkeypatch.setattr("runtime.urlopen", transport)
    response = supervisor._handle_gateway_request(
        "contract",
        {
            "request_id": request_id,
            "method": "capabilities.check",
            "capability": "games.read",
        },
    )
    assert response == {
        "api_version": "v1",
        "request_id": request_id,
        "payload": {"authorized": True},
    }


@pytest.mark.parametrize(
    "field,value", [("request_id", str(uuid4())), ("api_version", "v2")]
)
def test_gateway_rejects_wrong_version_or_correlation(
    supervisor, monkeypatch, field, value
):
    monkeypatch.setattr(
        "runtime.urlopen",
        lambda *args, **kwargs: io.BytesIO(
            json.dumps(
                {
                    "payload": {"authorized": True},
                    field: value,
                }
            ).encode()
        ),
    )
    with pytest.raises(RuntimePolicyError, match="correlation|unsupported API version"):
        supervisor._handle_gateway_request(
            "contract",
            {
                "method": "capabilities.check",
                "capability": "games.read",
            },
        )


def test_gateway_retains_permission_error_and_correlation_across_http(
    supervisor, monkeypatch
):
    request_id = str(uuid4())
    envelope = {
        "api_version": "v1",
        "request_id": request_id,
        "code": "forbidden",
        "message": "permission games.read has not been granted",
    }

    def transport(request, **kwargs):
        raise HTTPError(
            request.full_url,
            403,
            "Forbidden",
            {},
            io.BytesIO(json.dumps({"error": envelope}).encode()),
        )

    monkeypatch.setattr("runtime.urlopen", transport)
    request = {
        "request_id": request_id,
        "method": "games.list",
        "capability": "games.read",
    }
    with pytest.raises(RuntimeGatewayError) as failure:
        supervisor._handle_gateway_request("contract", request)
    response = gateway_error_response(failure.value, request)
    assert response["error"] == envelope["message"]
    assert response["error_detail"] == envelope
    assert response["request_id"] == request_id


def test_gateway_version_rejection_precedes_storage_and_http(supervisor, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Incompatible protocol must not reach host or storage")

    monkeypatch.setattr("runtime.urlopen", forbidden)
    monkeypatch.setattr(supervisor, "_storage", forbidden)
    with pytest.raises(RuntimeGatewayError) as failure:
        supervisor._handle_gateway_request(
            "contract",
            {
                "api_version": "v2",
                "method": "storage.put",
                "capability": "plugin.storage",
                "payload": {"key": "data", "value": "denied"},
            },
        )
    assert failure.value.envelope["code"] == "incompatible"


def test_gateway_network_failure_has_correlated_unavailable_error(
    supervisor, monkeypatch
):
    def unavailable(*args, **kwargs):
        raise TimeoutError("private transport details")

    monkeypatch.setattr("runtime.urlopen", unavailable)
    request = {"method": "games.list", "capability": "games.read"}
    with pytest.raises(RuntimeGatewayError) as failure:
        supervisor._handle_gateway_request("contract", request)
    response = gateway_error_response(failure.value, request)
    assert response["error_detail"]["code"] == "unavailable"
    assert response["request_id"] == request["request_id"]
    assert "private transport" not in response["error"]
