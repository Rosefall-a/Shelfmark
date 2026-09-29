"""Minimal isolated Plugin Runtime process boundary."""

from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class RuntimeHandler(BaseHTTPRequestHandler):
    """Expose only a health endpoint until the gateway is implemented."""

    server_version = "UnnamedTrackingPluginRuntime/0.1"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    """Run the runtime bootstrap process."""
    host = os.environ.get("PLUGIN_RUNTIME_HOST", "0.0.0.0")
    port = int(os.environ.get("PLUGIN_RUNTIME_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), RuntimeHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
