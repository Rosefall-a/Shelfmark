from __future__ import annotations

import json
import os
import secrets
import subprocess
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

CONFIG_PATH = ROOT / "src" / "devcontainer" / ".env"

ROOT = Path(os.environ.get("DEVCONTAINER_WORKSPACE", "/workspace"))
CONTROL_PORT = int(os.environ.get("DEVCONTAINER_CONTROL_PORT", "9000"))
DOCS_PORT = int(os.environ.get("DEVCONTAINER_DOCS_PORT", "999"))
DEV_PROJECT = os.environ.get("DEVCONTAINER_DEV_PROJECT", "uta-debug-dev")
PROD_PROJECT = os.environ.get("DEVCONTAINER_PROD_PROJECT", "uta-debug-prod")
PROD_PORT = int(os.environ.get("DEVCONTAINER_PROD_PORT", "8180"))
TOKEN = secrets.token_urlsafe(24)

STACKS = {
    "dev": {
        "name": "Development",
        "project": DEV_PROJECT,
        "compose": ROOT / "src" / "devcontainer" / "compose.dev.yaml",
        "url": "http://host.docker.internal:5173/",
    },
    "prod": {
        "name": "Production-like",
        "project": PROD_PROJECT,
        "compose": ROOT / "src" / "devcontainer" / "compose.prod.yaml",
        "url": f"http://host.docker.internal:{PROD_PORT}/",
    },
}

ACTIONS = {"start", "stop", "reset", "logs", "health", "status"}
CONFIG_FIELDS = {
    "db_user": "DEV_POSTGRES_USER", "db_password": "DEV_POSTGRES_PASSWORD",
    "db_name": "DEV_POSTGRES_DB", "secret_key": "DEV_SECRET_KEY",
    "admin_username": "DEV_PRIMARY_USER_USERNAME", "admin_email": "DEV_PRIMARY_USER_EMAIL",
    "admin_password": "DEV_PRIMARY_USER_PASSWORD", "auth_cookie_secure": "DEV_AUTH_COOKIE_SECURE",
}



def load_config() -> dict[str, Any]:
    values: dict[str, str] = {}
    if CONFIG_PATH.is_file():
        for line in CONFIG_PATH.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key] = value
    result: dict[str, Any] = {}
    defaults = {
        "db_user": "unnamed_tracking", "db_password": "debug-password", "db_name": "unnamed_tracking",
        "secret_key": "devcontainer-not-for-production", "admin_username": "admin",
        "admin_email": "admin@example.invalid", "admin_password": "debug-admin-password",
        "auth_cookie_secure": "false",
    }
    for field, env_key in CONFIG_FIELDS.items():
        value = values.get(env_key, os.environ.get(env_key, defaults[field]))
        result[field] = value.lower() == "true" if field == "auth_cookie_secure" else value
    return result


def save_config(values: dict[str, Any]) -> dict[str, Any]:
    current = load_config()
    for field in CONFIG_FIELDS:
        if field in values:
            current[field] = values[field]
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Shared developer environment configuration."]
    for field, env_key in CONFIG_FIELDS.items():
        value = str(current[field]).lower() if isinstance(current[field], bool) else str(current[field])
        lines.append(f"{env_key}={value}")
    CONFIG_PATH.write_text("\n".join(lines) + "\n")
    return current

def compose_args(environment: str, action: str) -> list[str]:
    if environment not in STACKS:
        raise ValueError("unknown environment")
    if action not in ACTIONS:
        raise ValueError("unknown action")
    stack = STACKS[environment]
    commands = {
        "start": ["up", "-d", "--build"],
        "stop": ["down", "--remove-orphans"],
        "reset": ["down", "--volumes", "--remove-orphans"],
        "logs": ["logs", "--tail", "120"],
        "status": ["ps"],
        "health": ["ps"],
    }
    return [
        "docker",
        "compose",
        "--project-name",
        stack["project"],
        "-f",
        str(stack["compose"]),
        *commands[action],
    ]


def run_command(args: list[str], timeout: int = 120) -> tuple[int, str]:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=os.environ.copy(),
    )
    output = (completed.stdout + completed.stderr).strip()
    return completed.returncode, output[-12000:]


def probe(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return {"state": "healthy", "status": response.status}
    except urllib.error.HTTPError as exc:
        return {"state": "reachable", "status": exc.code}
    except Exception as exc:
        return {"state": "unreachable", "error": type(exc).__name__}


def status(environment: str) -> dict[str, Any]:
    stack = STACKS[environment]
    code, output = run_command(compose_args(environment, "status"), timeout=20)
    return {
        "environment": environment,
        "name": stack["name"],
        "project": stack["project"],
        "compose_valid": code == 0,
        "containers": output,
        "endpoint": probe(stack["url"]),
        "endpoint_url": stack["url"].replace("host.docker.internal", "localhost"),
    }


def docs_process() -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["mkdocs", "serve", "-a", f"0.0.0.0:{DOCS_PORT}"],
        cwd=ROOT / "wiki",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        text=True,
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "UnnamedTrackingDevcontainer/1.0"

    def _json(self, payload: Any, status_code: int = 200) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    def _authorized(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-Devcontainer-Token", ""), TOKEN)

    def do_GET(self) -> None:
        if self.path == "/":
            html = (Path(__file__).with_name("index.html").read_text()).replace(
                "</head>", f"<meta name='devcontainer-token' content='{TOKEN}'></head>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html.encode())))
            self.end_headers()
            self.wfile.write(html.encode())
            return
        if self.path == "/style.css":
            data = Path(__file__).with_name("style.css").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/css")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path == "/app.js":
            data = Path(__file__).with_name("app.js").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path == "/api/environment":
            self._json(load_config())
            return
        if self.path == "/api/status":
            self._json({key: status(key) for key in STACKS})
            return
        if self.path == "/health":
            code, _ = run_command(["docker", "info"], 5)
            self._json({"status": "ok", "docker": code == 0})
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path not in {"/api/action", "/api/environment"} or not self._authorized():
            self._json({"error": "unauthorized"}, 403)
            return
        try:
            body = self._body()
            if self.path == "/api/environment":
                self._json(save_config(body))
                return
            environment = body.get("environment")
            action = body.get("action")
            if environment not in STACKS or action not in ACTIONS:
                raise ValueError("invalid environment or action")
            code, output = run_command(compose_args(environment, action))
            self._json({"ok": code == 0, "output": output}, 200 if code == 0 else 409)
        except (ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)
        except subprocess.TimeoutExpired:
            self._json({"error": "command timed out"}, 504)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    docs = docs_process()
    try:
        server = ThreadingHTTPServer(("0.0.0.0", CONTROL_PORT), Handler)
        server.serve_forever()
    finally:
        docs.terminate()
        docs.wait(timeout=5)


if __name__ == "__main__":
    main()
