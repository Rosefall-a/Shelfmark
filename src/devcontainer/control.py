from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("DEVCONTAINER_WORKSPACE", "/workspace"))
CONFIG_PATH = ROOT / "src" / "devcontainer" / ".env"
INSTANCES_PATH = ROOT / "src" / "devcontainer" / ".instances.json"
CONTROL_PORT = int(os.environ.get("DEVCONTAINER_CONTROL_PORT", "9000"))
DOCS_PORT = int(os.environ.get("DEVCONTAINER_DOCS_PORT", "999"))
TOKEN = secrets.token_urlsafe(24)

DEFAULT_INSTANCES = [
    {"id": "dev-main", "name": "Development", "environment": "dev", "project": "uta-debug-dev",
     "port": 5173, "build_mode": "local", "backend_image": "unnamed_tracking_app-dev-backend:local",
     "frontend_image": "unnamed_tracking_app-dev-frontend:local"},
    {"id": "prod-main", "name": "Production-like", "environment": "prod", "project": "uta-debug-prod",
     "port": 8180, "build_mode": "local", "image": "unnamed_tracking_app:devcontainer-prod"},
]

ACTIONS = {"start", "stop", "reset", "rebuild", "status", "health", "logs"}
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
CONFIG_FIELDS = {
    "db_user": "DEV_POSTGRES_USER", "db_password": "DEV_POSTGRES_PASSWORD",
    "db_name": "DEV_POSTGRES_DB", "secret_key": "DEV_SECRET_KEY",
    "admin_username": "DEV_PRIMARY_USER_USERNAME", "admin_email": "DEV_PRIMARY_USER_EMAIL",
    "admin_password": "DEV_PRIMARY_USER_PASSWORD", "auth_cookie_secure": "DEV_AUTH_COOKIE_SECURE",
}


def load_instances() -> list[dict[str, Any]]:
    if not INSTANCES_PATH.is_file():
        return [dict(item) for item in DEFAULT_INSTANCES]
    try:
        value = json.loads(INSTANCES_PATH.read_text())
        if not isinstance(value, list):
            raise ValueError
        return value
    except (OSError, ValueError, json.JSONDecodeError):
        return [dict(item) for item in DEFAULT_INSTANCES]


def save_instances(instances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    INSTANCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    INSTANCES_PATH.write_text(json.dumps(instances, indent=2) + "\n")
    return instances


def validate_instance(instance: dict[str, Any]) -> dict[str, Any]:
    environment = instance.get("environment")
    if environment not in {"dev", "prod"}:
        raise ValueError("environment must be dev or prod")
    project = str(instance.get("project", "")).strip()
    if not PROJECT_RE.fullmatch(project):
        raise ValueError("project must use lowercase letters, numbers, dashes, or underscores")
    port = int(instance.get("port", 0))
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    build_mode = instance.get("build_mode", "local")
    if build_mode not in {"local", "image"}:
        raise ValueError("build_mode must be local or image")
    result = dict(instance)
    result["project"] = project
    result["port"] = port
    result["build_mode"] = build_mode
    result["name"] = str(result.get("name") or project)
    result["id"] = str(result.get("id") or project)
    return result


def validate_instances(instances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(instances, list) or not instances:
        raise ValueError("at least one instance is required")
    result = [validate_instance(item) for item in instances]
    if len({x["id"] for x in result}) != len(result):
        raise ValueError("instance ids must be unique")
    if len({x["project"] for x in result}) != len(result):
        raise ValueError("project names must be unique")
    if len({x["port"] for x in result}) != len(result):
        raise ValueError("application ports must be unique")
    return result


def load_config() -> dict[str, Any]:
    values: dict[str, str] = {}
    if CONFIG_PATH.is_file():
        for line in CONFIG_PATH.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key] = value
    defaults = {
        "db_user": "unnamed_tracking", "db_password": "debug-password", "db_name": "unnamed_tracking",
        "secret_key": "devcontainer-not-for-production", "admin_username": "admin",
        "admin_email": "admin@example.invalid", "admin_password": "debug-admin-password",
        "auth_cookie_secure": "false",
    }
    result: dict[str, Any] = {}
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


def instance_by_id(instance_id: str) -> dict[str, Any]:
    for instance in load_instances():
        if instance["id"] == instance_id:
            return instance
    raise ValueError("unknown instance")


def compose_env(instance: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    env["DEVCONTAINER_APP_PORT"] = str(instance["port"])
    env["DEV_PULL_POLICY"] = "build" if instance["build_mode"] == "local" else "always"
    if instance["environment"] == "prod":
        env["PROD_IMAGE"] = instance.get("image") or "ghcr.io/rosefall-a/unnamed_tracking_app:latest"
    else:
        env["DEV_BACKEND_IMAGE"] = instance.get("backend_image", "unnamed_tracking_app-dev-backend:local")
        env["DEV_FRONTEND_IMAGE"] = instance.get("frontend_image", "unnamed_tracking_app-dev-frontend:local")
    return env


def compose_args(instance: dict[str, Any], action: str) -> list[str]:
    if action not in ACTIONS:
        raise ValueError("unknown action")
    compose = ROOT / "src" / "devcontainer" / (
        "compose.dev.yaml" if instance["environment"] == "dev" else "compose.prod.yaml"
    )
    command = {
        "start": ["up", "-d"], "stop": ["down", "--remove-orphans"],
        "reset": ["down", "--volumes", "--remove-orphans"], "rebuild": ["up", "-d"],
        "status": ["ps"], "health": ["ps"], "logs": ["logs", "--tail", "160"],
    }[action]
    if action in {"start", "rebuild"}:
        command += (["--build", "--pull", "never"] if instance["build_mode"] == "local"
                    else ["--no-build", "--pull", "always"])
    return [
        "docker", "compose", "--env-file", str(CONFIG_PATH), "--project-name", instance["project"],
        "-f", str(compose), *command,
    ]


def run_command(args: list[str], timeout: int = 120, environment: dict[str, str] | None = None) -> tuple[int, str]:
    completed = subprocess.run(
        args, cwd=ROOT, check=False, capture_output=True, text=True, timeout=timeout,
        env=environment or os.environ.copy(),
    )
    output = (completed.stdout + completed.stderr).strip()
    return completed.returncode, output[-16000:]


def probe(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return {"state": "healthy", "status": response.status}
    except urllib.error.HTTPError as exc:
        return {"state": "reachable", "status": exc.code}
    except Exception as exc:
        return {"state": "unreachable", "error": type(exc).__name__}


def status(instance: dict[str, Any]) -> dict[str, Any]:
    code, output = run_command(compose_args(instance, "status"), 20, compose_env(instance))
    return {
        **instance, "compose_valid": code == 0, "containers": output,
        "endpoint": probe(f"http://host.docker.internal:{instance['port']}/"),
        "endpoint_url": f"http://localhost:{instance['port']}/",
    }


def docs_process() -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["mkdocs", "serve", "-a", f"0.0.0.0:{DOCS_PORT}"], cwd=ROOT / "wiki",
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, text=True,
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "UnnamedTrackingDevcontainer/1.1"

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
            html = Path(__file__).with_name("index.html").read_text()
            html = html.replace("</head>", f"<meta name='devcontainer-token' content='{TOKEN}'></head>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html.encode())))
            self.end_headers()
            self.wfile.write(html.encode())
            return
        if self.path in {"/style.css", "/app.js"}:
            path = Path(__file__).with_name(self.path.lstrip("/"))
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/css" if self.path.endswith(".css") else "application/javascript")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path == "/api/environment":
            self._json(load_config())
        elif self.path == "/api/instances":
            self._json(load_instances())
        elif self.path == "/api/status":
            self._json([status(item) for item in load_instances()])
        elif self.path == "/health":
            code, _ = run_command(["docker", "info"], 5)
            self._json({"status": "ok", "docker": code == 0})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        if not self._authorized():
            self._json({"error": "unauthorized"}, 403)
            return
        try:
            body = self._body()
            if self.path == "/api/action":
                instance = instance_by_id(str(body.get("instance_id")))
                action = body.get("action")
                if action not in ACTIONS:
                    raise ValueError("invalid action")
                code, output = run_command(
                    compose_args(instance, action),
                    300 if action in {"start", "rebuild"} else 120,
                    compose_env(instance),
                )
                self._json({"ok": code == 0, "output": output}, 200 if code == 0 else 409)
                return
            if self.path == "/api/instances":
                instances = load_instances()
                instance = validate_instance(body)
                if any(item["id"] == instance["id"] for item in instances):
                    raise ValueError("instance id already exists")
                instances.append(instance)
                self._json(save_instances(validate_instances(instances)))
                return
            raise ValueError("unknown endpoint")
        except (ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)
        except subprocess.TimeoutExpired:
            self._json({"error": "command timed out"}, 504)

    def do_PUT(self) -> None:
        if not self._authorized():
            self._json({"error": "unauthorized"}, 403)
            return
        try:
            body = self._body()
            if self.path == "/api/environment":
                self._json(save_config(body))
                return
            if self.path == "/api/instances":
                instance = validate_instance(body)
                instances = [item for item in load_instances() if item["id"] != instance["id"]]
                instances.append(instance)
                self._json(save_instances(validate_instances(instances)))
                return
            raise ValueError("unknown endpoint")
        except (ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)

    def do_DELETE(self) -> None:
        if self.path != "/api/instances" or not self._authorized():
            self._json({"error": "unauthorized"}, 403)
            return
        try:
            instance_id = str(self._body().get("id"))
            instances = [item for item in load_instances() if item["id"] != instance_id]
            self._json(save_instances(validate_instances(instances)))
        except (ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)

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
