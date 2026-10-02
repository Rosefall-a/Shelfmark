import io
from urllib.error import HTTPError

import pytest

from src.plugin_api import outbound


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://name:secret@host",
        "http://host:bad",
        "http://host\n/x",
        "http://host/#secret",
    ],
)
def test_invalid_url_never_reaches_transport(monkeypatch, url):
    monkeypatch.setattr(
        outbound, "build_opener", lambda *args: pytest.fail("invalid URL reached HTTP")
    )
    with pytest.raises(ValueError):
        outbound.outbound_json({"url": url})


def test_header_controls_redirects_timeout_and_bounded_response(monkeypatch):
    class Response(io.BytesIO):
        def read(self, n=-1):
            assert n == outbound.MAX_BYTES + 1
            return super().read(n)

    class Opener:
        def open(self, request, timeout):
            assert timeout == 8
            assert request.headers["Authorization"] == "secret"
            return Response(b'{"Items":[]}')

    monkeypatch.setattr(outbound, "build_opener", lambda *args: Opener())
    assert outbound.outbound_json(
        {"url": "https://host/Items", "headers": {"Authorization": "secret"}}
    )["data"] == {"Items": []}
    with pytest.raises(ValueError, match="Redirect"):
        outbound.NoRedirects().redirect_request(None, None, 302, "", {}, "https://other")
    with pytest.raises(ValueError, match="headers"):
        outbound.outbound_json({"url": "https://host", "headers": {"Host": "other"}})


def test_server_errors_do_not_echo_remote_secrets(monkeypatch):
    class Opener:
        def open(self, *args, **kwargs):
            raise HTTPError("https://secret", 503, "secret", {}, io.BytesIO(b"secret"))

    monkeypatch.setattr(outbound, "build_opener", lambda *args: Opener())
    assert outbound.outbound_json({"url": "https://host"}) == {
        "status": 503,
        "error": "Remote server rejected the request.",
    }


@pytest.mark.parametrize("body", [b"x" * (outbound.MAX_BYTES + 1), b"invalid", b'"unexpected"'])
def test_malformed_and_oversized_responses(monkeypatch, body):
    class Opener:
        def open(self, *args, **kwargs):
            return io.BytesIO(body)

    monkeypatch.setattr(outbound, "build_opener", lambda *args: Opener())
    with pytest.raises(ValueError):
        outbound.outbound_json({"url": "https://host"})
