import io
import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.error import URLError

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
        status = 200

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


@pytest.mark.parametrize(
    "body",
    [b"x" * (outbound.MAX_BYTES + 1), b"invalid", b'"unexpected"'],
    ids=["oversized", "invalid-json", "scalar-string"],
)
def test_malformed_and_oversized_responses(monkeypatch, body):
    class Opener:
        def open(self, *args, **kwargs):
            response = io.BytesIO(body)
            response.status = 200
            return response

    monkeypatch.setattr(outbound, "build_opener", lambda *args: Opener())
    with pytest.raises(ValueError):
        outbound.outbound_json({"url": "https://host"})


def test_real_json_post_preserves_status_and_does_not_follow_redirects():
    received = []

    class Server(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            assert self.headers["Content-Type"] == "application/json"
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(201)
            self.end_headers()
            self.wfile.write(b'{"Code":"123456"}')

        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "/credential-leak")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        assert outbound.outbound_json(
            {"url": url, "method": "POST", "body": {"Username": "test"}}
        ) == {"status": 201, "data": {"Code": "123456"}}
        with pytest.raises(ValueError, match="Redirect"):
            outbound.outbound_json({"url": url, "headers": {"Authorization": "fixture"}})
        assert received == [{"Username": "test"}]
    finally:
        server.shutdown()
        server.server_close()


def test_certificate_failure_is_reported_without_bypass(monkeypatch):
    class Opener:
        def open(self, *_args, **_kwargs):
            raise URLError(ssl.SSLCertVerificationError("private diagnostics"))

    monkeypatch.setattr(outbound, "build_opener", lambda *_args: Opener())
    result = outbound.outbound_json({"url": "https://host"})
    assert result["code"] == "certificate_untrusted" and "private" not in str(result)


def test_retry_after_is_bounded_and_remote_error_body_is_private(monkeypatch):
    class Opener:
        def open(self, *_args, **_kwargs):
            raise HTTPError(
                "https://host", 429, "secret", {"Retry-After": "999999"}, io.BytesIO(b"secret")
            )

    monkeypatch.setattr(outbound, "build_opener", lambda *_args: Opener())
    result = outbound.outbound_json({"url": "https://host"})
    assert result["retry_after_seconds"] == 3600 and "secret" not in str(result)
