"""Cross-repository acceptance using official builds, PostgreSQL and real workers.

Run only against a disposable migrated database. The release sequence uses the
external repository's builder and a disposable publisher. Only acquisition of
the simulated catalogue is substituted; official URLs, runtime HTTP, permission
checks, workers, gateway, storage and lifecycle transactions remain real.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

HOST = Path(__file__).resolve().parents[1]
PLUGIN = "example.jellyfin-media-sync"
FIXTURE_BASE = "https://raw.githubusercontent.com/Rosefall-a/unnamed_tracking_app_plugins/integration-fixture"
PASSWORD = "Integration-test-password1!"


def available_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_until(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except (httpx.HTTPError, OSError):
            pass
        time.sleep(0.2)
    raise AssertionError("Timed out waiting for acceptance condition")


def configure_downloads(work):
    sys.path.insert(0, str(HOST / "src/backend"))
    from src.api.routes import plugins

    original = plugins._download_remote_file

    async def download(url, *, json_document=False):
        if not url.startswith(FIXTURE_BASE + "/"):
            return await original(url, json_document=json_document)
        relative = url.removeprefix(FIXTURE_BASE + "/")
        source = work / "release-source" / relative
        assert source.resolve().is_relative_to((work / "release-source").resolve())
        data = source.read_bytes()
        with tempfile.NamedTemporaryFile(delete=False) as stream:
            stream.write(data)
            path = Path(stream.name)
        return path, source.name, len(data)

    plugins._download_remote_file = download


def serve_host(work, port):
    sys.path.insert(0, str(HOST / "src/backend"))
    import uvicorn
    from src.main import app

    configure_downloads(work)
    uvicorn.run(app, host="0.0.0.0", port=port)


def serve_runtime(work, port):
    sys.path.insert(0, str(HOST / "src/plugin-runtime"))
    from runtime import PluginRegistry, PluginSupervisor, RuntimeHandler, RuntimeServer

    supervisor = PluginSupervisor(work / "workers", work / "runtime/.storage")
    supervisor.probe_isolation()
    registry = PluginRegistry(work / "runtime", supervisor)
    server = RuntimeServer(("0.0.0.0", port), RuntimeHandler)
    server.registry = registry
    registry.restore_enabled()
    try:
        server.serve_forever()
    finally:
        supervisor.stop_all()


async def automatic_check():
    sys.path.insert(0, str(HOST / "src/backend"))
    from sqlalchemy import select
    from src.main import app  # noqa: F401 - initialize the complete model registry
    from src.api.routes import plugins
    from src.database.models.user import User
    from src.database.session import SessionLocal

    configure_downloads(Path(os.environ["INTEGRATION_WORK_ROOT"]))
    async with SessionLocal() as db:
        admin = await db.scalar(
            select(User).where(User.username == os.environ["PRIMARY_USER_USERNAME"])
        )
        return await plugins.run_automatic_plugin_updates(db, admin)


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def commit(root, message):
    git(root, "add", ".")
    git(root, "commit", "-m", message)


def prepare_releases(plugins_root, work):
    root = work / "release-source"
    root.mkdir()
    for name in ("tools", "sdk", "publishers"):
        shutil.copytree(
            plugins_root / name,
            root / name,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    for name in ("jellyfin-media-sync", "help-button"):
        shutil.copytree(
            plugins_root / "examples" / name,
            root / "examples" / name,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    shutil.copyfile(plugins_root / ".gitignore", root / ".gitignore")
    help_manifest = root / "examples/help-button/manifest.json"
    help_metadata = json.loads(help_manifest.read_text())
    help_metadata["plugin_id"] = "example.integration-help"
    help_metadata["name"] = "Integration catalogue help"
    help_manifest.write_text(json.dumps(help_metadata))
    help_ui = root / "examples/help-button/ui.json"
    help_ui.write_text(
        help_ui.read_text().replace("example.help-button", "example.integration-help")
    )
    (root / "catalogue.json").write_text(
        json.dumps({"name": "Lifecycle acceptance", "base_url": FIXTURE_BASE})
    )
    key = Ed25519PrivateKey.generate()
    public = base64.b64encode(key.public_key().public_bytes_raw()).decode()
    record = {
        "key_id": "integration-disposable",
        "publisher": "Unnamed Tracking Official",
        "public_key_file": "integration.public-key.b64",
        "public_key_b64": public,
        "public_key_sha256": hashlib.sha256(
            key.public_key().public_bytes_raw()
        ).hexdigest(),
        "status": "active",
        "plugin_id_prefixes": ["example."],
    }
    (root / "publishers/integration.public-key.b64").write_text(public)
    (root / "publishers/registry.json").write_text(
        json.dumps({"schema_version": 1, "publishers": [record]})
    )
    trust = json.loads(
        (HOST / "src/backend/src/plugin_api/trusted_publishers.json").read_text()
    )
    trust["publishers"].append(record)
    (work / "trusted.json").write_text(json.dumps(trust))
    env = {
        **os.environ,
        "PLUGIN_SIGNING_KEY_ID": record["key_id"],
        "PLUGIN_SIGNING_KEY_B64": base64.b64encode(key.private_bytes_raw()).decode(),
    }
    git(root, "init")
    git(root, "config", "user.name", "Integration test")
    git(root, "config", "user.email", "integration@example.invalid")
    commit(root, "feat: initialize release acceptance")
    return root, env


def build(root, env):
    result = subprocess.run(
        [sys.executable, str(root / "tools/build_packages.py"), "--publish"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    catalogue = json.loads((root / "list.json").read_text())
    commit(root, "chore: publish acceptance packages")
    return next(item for item in catalogue["plugins"] if item["plugin_id"] == PLUGIN)


class Jellyfin(BaseHTTPRequestHandler):
    def do_GET(self):
        assert "IntegrationToken123" in self.headers.get("Authorization", "")
        data = json.dumps(
            {
                "Items": [
                    {
                        "Id": "integration-movie",
                        "Name": "Integration Movie",
                        "Type": "Movie",
                        "UserData": {"Played": True},
                    }
                ],
                "TotalRecordCount": 1,
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


def acceptance(plugins_root, work, browser=False):
    root, signing_env = prepare_releases(plugins_root, work)
    entry = build(root, signing_env)
    host_port, runtime_port = available_port(), available_port()
    runtime_url = f"http://127.0.0.1:{runtime_port}"
    env = {
        **os.environ,
        "PRIMARY_USER_USERNAME": "integration-" + uuid4().hex,
        "PRIMARY_USER_EMAIL": uuid4().hex + "@example.invalid",
        "PRIMARY_USER_PASSWORD": PASSWORD,
        "PLUGIN_RUNTIME_URL": runtime_url,
        "PLUGIN_RUNTIME_TOKEN": uuid4().hex + uuid4().hex,
        "PLUGIN_GATEWAY_URL": f"http://127.0.0.1:{host_port}",
        "NONBUBBLE_ENV": "true",
        "PLUGIN_MANAGER_STATE_PATH": str(work / "manager.json"),
        "PLUGIN_CATALOGUE_REGISTRY": str(work / "catalogues.json"),
        "PLUGIN_TRUSTED_PUBLISHER_REGISTRY": str(work / "trusted.json"),
        "INTEGRATION_WORK_ROOT": str(work),
        "STARTUP_MODE": "testing",
        "DEBUG": "false",
    }
    logs = []
    processes = []

    def launch(mode, port):
        log = (work / f"{mode}-{len(logs)}.log").open("w")
        logs.append(log)
        process = subprocess.Popen(
            [
                sys.executable,
                __file__,
                "--work-root",
                str(work),
                "--mode",
                mode,
                "--port",
                str(port),
            ],
            env=env,
            cwd=HOST / "src/backend",
            stdout=log,
            stderr=log,
        )
        processes.append(process)
        return process

    def automatic():
        result = subprocess.run(
            [sys.executable, __file__, "--mode", "automatic"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout.strip().splitlines()[-1])

    def browser_check(phase, review=None):
        result = subprocess.run(
            [
                "node",
                str(HOST / "tools/check_plugin_manager_ui.mjs"),
                str(plugins_root),
                phase,
            ],
            env={**env, "INTEGRATION_REVIEW": json.dumps(review or {})},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        print(result.stdout, flush=True)

    runtime = launch("runtime", runtime_port)
    host = launch("host", host_port)
    jellyfin = ThreadingHTTPServer(("127.0.0.1", 0), Jellyfin)
    threading.Thread(target=jellyfin.serve_forever, daemon=True).start()
    try:
        with httpx.Client(base_url=env["PLUGIN_GATEWAY_URL"], timeout=45) as client:
            wait_until(
                lambda: (
                    client.post(
                        "/api/auth/login",
                        json={
                            "username_or_email": env["PRIMARY_USER_USERNAME"],
                            "password": PASSWORD,
                        },
                    ).status_code
                    == 200
                )
            )

            def request(method, path, expected=200, **kwargs):
                response = client.request(method, "/api/plugins" + path, **kwargs)
                assert response.status_code == expected, (
                    path,
                    response.status_code,
                    response.text,
                )
                return response.json() if response.content else None

            def current():
                return next(
                    item for item in request("GET", "") if item["plugin_id"] == PLUGIN
                )

            def action(name, values=None, expected=200):
                return request(
                    "POST",
                    f"/{PLUGIN}/actions/{name}",
                    expected,
                    json={"values": values or {}, "confirmed": True},
                )

            def source(item):
                return {
                    "url": item["url"],
                    "source_type": "catalogue",
                    "catalogue_url": FIXTURE_BASE + "/list.json",
                }

            # Official transport is real and every catalogue package is inspected.
            official = request("GET", "/catalog")
            for item in official:
                preview = request(
                    "POST",
                    "/install/preview-url",
                    json={
                        "url": item["url"],
                        "source_type": "catalogue",
                        "catalogue_url": "https://raw.githubusercontent.com/Rosefall-a/unnamed_tracking_app_plugins/main/list.json",
                    },
                )
                assert preview["version"] == item["version"]
                assert preview["digest"] == item["sha256"]
                assert preview["readme"] == item["readme"]
                assert preview["tags"] == item["tags"]
                assert preview["automatic_update"] == item["automatic_update"]
                assert preview["trust_status"] == "trusted"
            print(
                f"Official distribution: {len(official)} live packages verified",
                flush=True,
            )
            live_release = next(
                item for item in official if item["plugin_id"] == PLUGIN
            )
            live_source = {
                "url": live_release["url"],
                "source_type": "catalogue",
                "catalogue_url": "https://raw.githubusercontent.com/Rosefall-a/unnamed_tracking_app_plugins/main/list.json",
            }
            live_preview = request("POST", "/install/preview-url", json=live_source)
            request(
                "POST",
                "/install/url",
                201,
                params={
                    "approved_permissions": [
                        p["key"] for p in live_preview["permissions"]
                    ]
                },
                json=live_source,
            )
            assert current()["status"] == "running" and current()["health"] == "healthy"
            assert current()["version"] == live_release["version"]
            assert current()["source"]["type"] == "catalogue"
            assert request("GET", f"/{PLUGIN}/ui")["native_frontend"]
            request("DELETE", f"/{PLUGIN}", 204)
            print(
                "Live official Jellyfin package installation and healthy startup: passed",
                flush=True,
            )
            request(
                "POST",
                "/catalogues",
                201,
                json={"name": "Acceptance", "url": FIXTURE_BASE + "/list.json"},
            )
            assert len([c for c in request("GET", "/catalogues") if c["enabled"]]) >= 2
            combined = [
                item
                for catalogue in request("GET", "/catalogues")
                if catalogue["enabled"]
                for item in request(
                    "GET", "/catalog", params={"source": catalogue["url"]}
                )
            ]
            assert {item["plugin_id"] for item in official}.issubset(
                {item["plugin_id"] for item in combined}
            )
            assert "example.integration-help" in {
                item["plugin_id"] for item in combined
            }
            preview = request("POST", "/install/preview-url", json=source(entry))
            keys = [item["key"] for item in preview["permissions"]]
            assert all(
                item["risk"] in {"low", "medium", "high", "critical"}
                for item in preview["permissions"]
            )
            if browser:
                request("PATCH", "/catalogues/official", json={"enabled": False})
                browser_check("install", preview)
                request("PATCH", "/catalogues/official", json={"enabled": True})
            else:
                request(
                    "POST",
                    "/install/url",
                    201,
                    params={"approved_permissions": keys},
                    json=source(entry),
                )
            assert current()["status"] == "running" and current()["health"] == "healthy"
            assert current()["tags"] == entry["tags"]
            original_identity = current()["installation_id"]
            duplicate = request("POST", "/install/url", 409, json=source(entry))
            assert duplicate["detail"]["choices"] == [
                "update",
                "reinstall",
                "replace",
                "cancel",
            ]
            ui = request("GET", f"/{PLUGIN}/ui")
            assert ui["native_frontend"]
            asset = client.get(
                f"/api/plugins/{PLUGIN}/native-frontend/{ui['native_frontend']['entry']}"
            )
            assert asset.status_code == 200
            capabilities = request("GET", "/runtime/health")
            assert (
                capabilities["mechanism"] == "process"
                and not capabilities["sandbox_available"]
            )
            print(
                "Install, consent, real startup, native UI assets and reduced isolation: passed",
                flush=True,
            )
            config = {
                "server_url": f"http://127.0.0.1:{jellyfin.server_port}",
                "user_id": "a" * 32,
                "background_sync": False,
                "sync_interval_minutes": 15,
            }
            request("PUT", f"/{PLUGIN}/settings", json=config)
            assert action("save-token", {"api_key": "IntegrationToken123"})["ok"]
            assert action("sync-now")["queued"]
            wait_until(lambda: action("status").get("phase") == "complete", timeout=45)
            assert action("list-media")["media"]
            storage = work / "runtime/.storage" / PLUGIN
            baseline = {
                p.relative_to(storage): p.read_bytes()
                for p in storage.rglob("*")
                if p.is_file()
            }
            assert baseline

            def preserved():
                assert action("get-config")["server_url"] == config["server_url"]
                assert action("status")["phase"] == "complete"
                for path, content in baseline.items():
                    assert (storage / path).read_bytes() == content, path
                assert current()["installation_id"] == original_identity

            runtime.send_signal(signal.SIGINT)
            runtime.wait(timeout=10)
            runtime = launch("runtime", runtime_port)
            wait_until(lambda: current()["status"] == "running")
            preserved()
            host.send_signal(signal.SIGINT)
            host.wait(timeout=10)
            host = launch("host", host_port)
            wait_until(lambda: current()["status"] == "running")
            preserved()
            request("POST", f"/{PLUGIN}/disable")
            assert current()["status"] == "disabled"
            request("POST", f"/{PLUGIN}/enable")
            preserved()
            request("POST", f"/{PLUGIN}/reinstall", json={})
            preserved()
            print(
                "Jellyfin real sync, secrets, restart, disable/enable and preserving reinstall: passed",
                flush=True,
            )

            metadata_path = root / "examples/jellyfin-media-sync/release.json"
            metadata = json.loads(metadata_path.read_text())

            def release(*, automatic_update=True, introduced=False, broken=False):
                metadata["automatic_update"] = automatic_update
                metadata["release_notes"] = f"Acceptance release {uuid4().hex}"
                metadata_path.write_text(json.dumps(metadata))
                manifest_path = root / "examples/jellyfin-media-sync/manifest.json"
                if introduced:
                    manifest = json.loads(manifest_path.read_text())
                    ref = {"name": "games.read", "version": 1}
                    manifest["capabilities"].append(ref)
                    manifest["permissions"].append(
                        {"capability": ref, "rationale": "Acceptance permission delta"}
                    )
                    manifest_path.write_text(json.dumps(manifest))
                if broken:
                    path = root / "examples/jellyfin-media-sync/plugin.py"
                    path.write_text(
                        path.read_text().replace(
                            'request("lifecycle.ready", "lifecycle.ready", {})',
                            'raise RuntimeError("Acceptance startup failure")',
                        )
                    )
                commit(root, "fix: exercise release transition")
                return build(root, signing_env)

            second = release()
            updates = request("POST", "/updates/check")
            assert updates["available"] == 1
            request("POST", f"/{PLUGIN}/update/preview-url", json=source(second))
            if browser:
                browser_check("update")
            else:
                request("POST", f"/{PLUGIN}/update/url", json=source(second))
            assert current()["version"] == second["version"]
            preserved()
            request("POST", f"/{PLUGIN}/rollback", json={})
            assert current()["version"] == entry["version"]
            preserved()
            request("POST", f"/{PLUGIN}/update/url", json=source(second))
            request(
                "PUT",
                "/manager-settings",
                json={"automatic_updates": True, "retained_versions": 2},
            )
            manual = release(automatic_update=False)
            assert automatic()["installed"] == 0
            assert current()["version"] == second["version"]
            assert current()["staged_update"]["automatic_update"] is False
            auto = release(automatic_update=True)
            assert automatic()["installed"] == 1
            assert current()["version"] == auto["version"]
            preserved()
            staged = release(introduced=True)
            assert automatic()["installed"] == 0
            assert (
                current()["version"] == auto["version"]
                and current()["status"] == "running"
            )
            assert current()["staged_update"]["status"] == "awaiting_permissions"
            staged_preview = request("POST", f"/{PLUGIN}/update/staged/preview")
            request(
                "POST",
                f"/{PLUGIN}/update/staged",
                json={
                    "approved_permissions": ["games.read:v1"],
                    "expected_digest": staged_preview["digest"],
                },
            )
            assert current()["version"] == staged["version"]
            preserved()
            failure = release(broken=True)
            assert automatic()["failed"] == 1
            assert (
                current()["version"] == staged["version"]
                and current()["status"] == "running"
            )
            assert current()["last_update_error"]
            notifications = client.get("/api/notifications").json()
            assert "Plugin update failed:" in json.dumps(notifications)
            preserved()
            assert len(current()["history"]) == 2
            request(
                "PUT",
                "/manager-settings",
                json={"automatic_updates": False, "retained_versions": 1},
            )
            assert len(current()["history"]) == 1
            print(
                "Update, rollback, permission staging, opt-out/opt-in, failed real startup, notification and retention: passed",
                flush=True,
            )
            request("POST", f"/{PLUGIN}/permissions/revoke")
            action("get-config", expected=403)
            request(
                "POST",
                f"/{PLUGIN}/permissions/grant",
                json={"approved_permissions": keys + ["games.read:v1"]},
            )
            preserved()
            for scope in (
                "plugins.read",
                "plugins.install",
                "plugins.update",
                "plugins.lifecycle",
                "plugins.permissions",
            ):
                token = request(
                    "POST",
                    "/management/tokens",
                    201,
                    json={"name": scope, "scopes": [scope]},
                )
                with httpx.Client(
                    base_url=env["PLUGIN_GATEWAY_URL"],
                    headers={"Authorization": "Bearer " + token["token"]},
                ) as remote:
                    for unrelated in (
                        "/api/auth/me",
                        "/api/game/list",
                        "/api/settings/appearance",
                    ):
                        assert remote.get(unrelated).status_code == 403
                    for required, method, path, body in (
                        ("plugins.read", "GET", "", None),
                        (
                            "plugins.install",
                            "POST",
                            "/install/preview-url",
                            source(failure),
                        ),
                        ("plugins.update", "POST", "/updates/check", None),
                        ("plugins.lifecycle", "POST", f"/{PLUGIN}/disable", None),
                        (
                            "plugins.permissions",
                            "POST",
                            f"/{PLUGIN}/permissions/preview",
                            None,
                        ),
                    ):
                        response = remote.request(
                            method, "/api/plugins" + path, json=body
                        )
                        assert response.status_code == (
                            200 if scope == required else 403
                        ), response.text
                        if required == "plugins.lifecycle" and scope == required:
                            request("POST", f"/{PLUGIN}/enable")
                request("DELETE", "/management/tokens/" + token["id"])
            request(
                "POST", f"/{PLUGIN}/reinstall", json={"purge": True, "confirmed": True}
            )
            # Purge clears settings and storage; regrant is explicit.
            request(
                "POST",
                f"/{PLUGIN}/permissions/grant",
                json={"approved_permissions": keys + ["games.read:v1"]},
            )
            request("POST", f"/{PLUGIN}/enable")
            assert action("get-config")["server_url"] == ""
            assert action("status").get("phase") != "complete"
            request("DELETE", f"/{PLUGIN}", 204)
            assert not storage.exists()
            assert not (work / "runtime/.configuration" / f"{PLUGIN}.json").exists()
            assert not request("GET", "")
            print(
                "Revocation/regrant, remote token confinement, confirmed purge and uninstall: passed",
                flush=True,
            )
    finally:
        jellyfin.shutdown()
        for process in reversed(processes):
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                process.wait(timeout=10)
        for log in logs:
            log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugins-root", type=Path)
    parser.add_argument("--work-root", type=Path)
    parser.add_argument(
        "--mode",
        choices=["acceptance", "host", "runtime", "automatic"],
        default="acceptance",
    )
    parser.add_argument("--port", type=int)
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Also exercise the built frontend with Playwright",
    )
    args = parser.parse_args()
    if args.mode == "automatic":
        print(json.dumps(asyncio.run(automatic_check())))
    elif args.mode == "host":
        serve_host(args.work_root, args.port)
    elif args.mode == "runtime":
        serve_runtime(args.work_root, args.port)
    else:
        assert args.plugins_root and args.work_root, (
            "Supply external plugins checkout and an empty work root"
        )
        args.work_root.mkdir(parents=True, exist_ok=False)
        acceptance(args.plugins_root.resolve(), args.work_root.resolve(), args.browser)


if __name__ == "__main__":
    main()
