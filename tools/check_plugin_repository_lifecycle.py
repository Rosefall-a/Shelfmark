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
import io
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
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from plugin_conformance import InstalledPluginConformance

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
    from src.api.routes import plugins
    from src.database.models.user import User
    from src.database.session import SessionLocal
    from src.main import app  # noqa: F401 - initialize the complete model registry

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
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    catalogue = json.loads((root / "list.json").read_text())
    commit(root, "chore: publish acceptance packages")
    return next(item for item in catalogue["plugins"] if item["plugin_id"] == PLUGIN)


class Jellyfin(BaseHTTPRequestHandler):
    watched = False

    def do_GET(self):
        from urllib.parse import parse_qs, urlsplit

        assert "IntegrationToken123" in self.headers.get("Authorization", "")
        path = urlsplit(self.path)
        if path.path == "/System/Info":
            data = {"Id": "fixture"}
        elif path.path == "/Users":
            data = [
                {"Id": "a" * 32, "Name": "Fixture user"},
                {"Id": "b" * 32, "Name": "Second fixture user"},
            ]
        elif path.path == "/Library/VirtualFolders":
            data = [
                {"ItemId": c * 32, "Name": n}
                for c, n in zip("123", ("Movies", "TV Shows", "Anime"))
            ]
        else:
            query = parse_qs(path.query)
            if "ParentId" not in query:
                # Preserve conformance for released v2 packages while companion
                # v3 source and additive host capabilities are reviewed separately.
                items = [
                    {
                        "Id": "4" * 32,
                        "Name": "Integration Movie",
                        "Type": "Movie",
                        "UserData": {"Played": True},
                    }
                ]
                offset = int(query["StartIndex"][0])
                data = {
                    "Items": items[offset : offset + 100],
                    "TotalRecordCount": len(items),
                }
                body = json.dumps(data).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)
                return
            library = query["ParentId"][0][0]
            roots = {
                "1": [("4", "Integration Movie", "Movie")],
                "2": [("5", "Integration TV", "Series")],
                "3": [("6", "Integration Anime", "Series")],
            }
            if query["IncludeItemTypes"] == ["Episode"]:
                items = (
                    []
                    if library == "1"
                    else [
                        {
                            "Id": format(7 + (library == "3") * 2 + i, "x") * 32,
                            "Name": "Episode " + str(i + 1),
                            "SeriesId": ("5" if library == "2" else "6") * 32,
                            "Type": "Episode",
                            "ParentIndexNumber": 1,
                            "IndexNumber": i + 1,
                            "UserData": {"Played": i == 0 or self.watched},
                        }
                        for i in range(2)
                    ]
                )
            else:
                items = [
                    {
                        "Id": c * 32,
                        "Name": title,
                        "Type": kind,
                        "UserData": {
                            "Played": self.watched,
                            "PlaybackPositionTicks": 100,
                        },
                    }
                    for c, title, kind in roots[library]
                ]
            offset = int(query["StartIndex"][0])
            data = {
                "Items": items[offset : offset + 100],
                "TotalRecordCount": len(items),
            }
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def acceptance(plugins_root, work, browser=False):
    def revision(root):
        # Exported source trees and Windows worktree mounts may lack usable Git metadata.
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    report = {
        "schema_version": 1,
        "status": "running",
        "plugin_id": PLUGIN,
        "browser": browser,
        "jellyfin_browser": bool(os.getenv("JELLYFIN_SCREENSHOT_DIR")),
        "host_commit": revision(HOST),
        "plugins_commit": revision(plugins_root),
        "passed": [],
    }

    def checkpoint(name):
        report["passed"].append(name)
        (work / "conformance.json").write_text(json.dumps(report, indent=2) + "\n")

    root, signing_env = prepare_releases(plugins_root, work)
    entry = build(root, signing_env)
    report.update(package_version=entry["version"], package_digest=entry["sha256"])
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
            check=False,
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
            check=False,
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

            conformance = InstalledPluginConformance(client, PLUGIN)
            request = conformance.request
            current = conformance.current
            action = conformance.action

            def source(item):
                return {
                    "url": item["url"],
                    "source_type": "catalogue",
                    "catalogue_url": FIXTURE_BASE + "/list.json",
                }

            # Invalid packages pass through the same public static preview path.
            request(
                "POST",
                "/install/preview",
                400,
                files={"file": ("invalid.utp", b"not an archive")},
            )
            candidate = root / "dist" / entry["package"]["filename"]
            for mutation in ("manifest", "digest"):
                buffer = io.BytesIO()
                with (
                    zipfile.ZipFile(candidate) as original,
                    zipfile.ZipFile(buffer, "w") as invalid,
                ):
                    for name in original.namelist():
                        content = original.read(name)
                        if name == "manifest.json":
                            manifest = json.loads(content)
                            if mutation == "manifest":
                                manifest["entrypoint"] = "../../host:main"
                            else:
                                manifest["integrity"]["sha256"] = "0" * 64
                            content = json.dumps(manifest).encode()
                        invalid.writestr(name, content)
                request(
                    "POST",
                    "/install/preview",
                    400,
                    files={"file": ("invalid.utp", buffer.getvalue())},
                )
            assert not request("GET", "")
            checkpoint("invalid package, manifest and digest rejected before execution")

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
            checkpoint(
                "official packages, hashes, signatures, compatibility and catalogue metadata"
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
            conformance.assert_ready()
            assert current()["version"] == live_release["version"]
            assert current()["source"]["type"] == "catalogue"
            assert request("GET", f"/{PLUGIN}/ui")["native_frontend"]
            request("DELETE", f"/{PLUGIN}", 204)
            print(
                "Live official Jellyfin package installation and healthy startup: passed",
                flush=True,
            )
            checkpoint("live official package install, gateway readiness and native UI")
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
            modern_sync = any(a["id"] == "save-master" for a in ui["actions"])
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
            checkpoint(
                "signed generated package, host risk review, approval and isolation diagnostics"
            )
            config = {
                "server_url": f"http://127.0.0.1:{jellyfin.server_port}",
                "user_id": "a" * 32,
                "background_sync": False,
                "sync_interval_minutes": 15,
            }
            if modern_sync:
                assert action(
                    "save-master",
                    {
                        "server_url": config["server_url"],
                        "api_key": "IntegrationToken123",
                    },
                )["ok"]
                assert action("test-connection")["ok"]
                assert action(
                    "save-mappings",
                    {
                        "mappings": {
                            "1" * 32: "movie",
                            "2" * 32: "tv_show",
                            "3" * 32: "anime",
                        }
                    },
                )["ok"]
                host_user = action("get-config")["host_user_id"]
                assert action(
                    "authorize-identity",
                    {"host_user_id": host_user, "user_id": "a" * 32},
                )["ok"]
                assert action("save-user", {"user_id": "a" * 32})["ok"]

                def synchronize():
                    assert action("sync-now")["queued"]
                    # Wait for a new completed attempt, not a stale previous status.
                    wait_until(
                        lambda: action("status").get("phase") == "syncing", timeout=20
                    )
                    wait_until(
                        lambda: action("status").get("phase") == "complete", timeout=60
                    )

                def media(kind):
                    response = client.get(f"/api/{kind}/list")
                    assert response.status_code == 200, response.text
                    return response.json()["items"]

                synchronize()
                films, shows, anime = media("movie"), media("tv"), media("anime")
                assert len(films) == len(shows) == len(anime) == 1
                assert films[0]["status"] == "IN_PROGRESS"
                assert shows[0]["status"] == anime[0]["status"] == "IN_PROGRESS"
                Jellyfin.watched = True
                synchronize()
                assert all(
                    media(kind)[0]["status"] == "WATCHED"
                    for kind in ("movie", "tv", "anime")
                )
                synchronize()
                assert all(len(media(kind)) == 1 for kind in ("movie", "tv", "anime"))
                movie_id = films[0]["id"]
                destination = request(
                    "POST",
                    f"/{PLUGIN}/actions/watch-now",
                    json={
                        "values": {},
                        "context": {
                            "kind": "media",
                            "resource_id": movie_id,
                            "resource_type": "movie",
                        },
                    },
                )
                assert (
                    destination["url"]
                    == config["server_url"] + "/web/index.html#!/details?id=" + "4" * 32
                )
                assert "IntegrationToken" not in json.dumps(destination)
                checkpoint(
                    "master config, approved user, mapped film/TV/anime, native completion, repeat sync and exact Watch Now"
                )
                # A different authenticated host user links their approved identity;
                # the worker must import into their scope, never the enabling admin's.
                second_name = "linked-" + uuid4().hex
                created = client.post(
                    "/api/auth/users",
                    json={
                        "username": second_name,
                        "email": uuid4().hex + "@example.invalid",
                        "password": PASSWORD,
                    },
                )
                assert created.status_code == 201, created.text
                second_user = created.json()["id"]
                with httpx.Client(
                    base_url=env["PLUGIN_GATEWAY_URL"], timeout=45
                ) as other:
                    assert (
                        other.post(
                            "/api/auth/login",
                            json={
                                "username_or_email": second_name,
                                "password": PASSWORD,
                            },
                        ).status_code
                        == 200
                    )
                    peer = InstalledPluginConformance(other, PLUGIN)
                    assert "master" not in peer.action("get-config")
                    denied = other.post(
                        f"/api/plugins/{PLUGIN}/actions/save-master",
                        json={"values": {"server_url": "https://unauthorized.example"}},
                    )
                    assert denied.status_code >= 400
                    assert (
                        action("get-config")["master"]["server_url"]
                        == config["server_url"]
                    )
                    denied = other.post(
                        f"/api/plugins/{PLUGIN}/actions/save-user",
                        json={"values": {"user_id": "a" * 32}},
                    )
                    assert denied.status_code >= 400
                    action(
                        "authorize-identity",
                        {"host_user_id": second_user, "user_id": "b" * 32},
                    )
                    assert peer.action("save-user", {"user_id": "b" * 32})["ok"]
                    assert peer.action("sync-now")["queued"]
                    wait_until(
                        lambda: peer.action("status").get("phase") == "complete",
                        timeout=90,
                    )
                    rows = other.get("/api/movie/list").json()["items"]
                    assert len(rows) == 1 and rows[0]["id"] != movie_id
                    own_destination = peer.request(
                        "POST",
                        f"/{PLUGIN}/actions/watch-now",
                        json={
                            "values": {},
                            "context": {
                                "kind": "media",
                                "resource_id": rows[0]["id"],
                                "resource_type": "movie",
                            },
                        },
                    )
                    assert own_destination["url"] == destination["url"]
                    unavailable = peer.request(
                        "POST",
                        f"/{PLUGIN}/actions/watch-now",
                        json={
                            "values": {},
                            "context": {
                                "kind": "media",
                                "resource_id": movie_id,
                                "resource_type": "movie",
                            },
                        },
                    )
                    assert unavailable["ok"] is False
                    assert len(media("movie")) == 1
                    peer.action("unlink-user")
                checkpoint(
                    "second-user delegation, administrator/identity denial and cross-user Watch Now isolation"
                )
                if os.getenv("JELLYFIN_SCREENSHOT_DIR"):
                    subprocess.run(
                        ["node", str(plugins_root / "tools/capture_jellyfin.mjs")],
                        env={
                            **env,
                            "JELLYFIN_HOST_ROOT": str(HOST),
                            "JELLYFIN_FRONTEND_PORT": str(available_port()),
                        },
                        check=True,
                    )
                    checkpoint("installed native UI and media-page screenshots")

            else:
                request("PUT", f"/{PLUGIN}/settings", json=config)
                assert action("save-token", {"api_key": "IntegrationToken123"})["ok"]
                assert action("sync-now")["queued"]
                wait_until(
                    lambda: action("status").get("phase") == "complete", timeout=45
                )
                assert action("list-media")["media"]
            storage = work / "runtime/.storage" / PLUGIN
            baseline = {
                p.relative_to(storage): p.read_bytes()
                for p in storage.rglob("*")
                if p.is_file()
                and p.relative_to(storage).as_posix() != "worker/position"
            }
            assert baseline

            def preserved():
                saved = action("get-config")
                assert (saved["master"] if modern_sync else saved)[
                    "server_url"
                ] == config["server_url"]
                assert action("status")["phase"] == "complete"
                for path, content in baseline.items():
                    assert (storage / path).read_bytes() == content, path
                assert current()["installation_id"] == original_identity

            runtime.send_signal(signal.SIGINT)
            runtime.wait(timeout=10)
            offline = current()
            assert offline["version"] == entry["version"]
            assert (
                offline["installation_id"] == original_identity and offline["enabled"]
            )
            assert offline["runtime_available"] is False
            assert offline["runtime"]["sandbox_available"] is False
            assert offline["runtime"]["mechanism"] == "unavailable"
            if browser:
                browser_check("offline")
            runtime = launch("runtime", runtime_port)
            wait_until(lambda: current()["status"] == "running")
            preserved()
            host.send_signal(signal.SIGINT)
            host.wait(timeout=10)
            host = launch("host", host_port)
            wait_until(lambda: current()["status"] == "running")
            preserved()

            def persistence_probe():
                preserved()
                return {p: (storage / p).read_bytes() for p in baseline}

            conformance.preserving_lifecycle(persistence_probe)
            preserved()
            print(
                "Jellyfin real sync, secrets, restart, disable/enable and preserving reinstall: passed",
                flush=True,
            )
            checkpoint(
                "operation, data and secrets, restart, offline inventory, stop/start, disable/enable and preserving reinstall"
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
            release(automatic_update=False)
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
            assert "games.read" not in current()["granted_capabilities"]
            denied = request(
                "POST", f"/{PLUGIN}/update/staged", json={"confirmed": True}
            )
            assert denied["status"] == "denied"
            assert automatic()["installed"] == 0
            assert current()["staged_update"]["status"] == "denied"
            assert current()["version"] == auto["version"]
            assert "games.read" not in current()["granted_capabilities"]
            preserved()
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
            checkpoint(
                "update without new scopes, rollback, staged new scopes, denial and explicit approval"
            )
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
            checkpoint(
                "failed real startup restores previous release, data and grants; update policy and history retention"
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
                    for method, path, body in (
                        ("POST", f"/{PLUGIN}/actions/status", {"values": {}}),
                        ("GET", f"/{PLUGIN}/ui", None),
                        ("PUT", f"/{PLUGIN}/settings", config),
                        (
                            "PUT",
                            f"/{PLUGIN}/secrets/probe",
                            {"key": "probe", "value": "denied"},
                        ),
                    ):
                        response = remote.request(
                            method, "/api/plugins" + path, json=body
                        )
                        assert response.status_code == 403, (
                            scope,
                            method,
                            path,
                            response.status_code,
                        )
                    assert (
                        remote.post(
                            "/api/auth/api-keys", json={"name": "denied"}
                        ).status_code
                        == 403
                    )
                    if scope in {"plugins.install", "plugins.update"}:
                        # Operation scope alone cannot approve new privileges.
                        path = (
                            "/install/url"
                            if scope == "plugins.install"
                            else f"/{PLUGIN}/update/staged"
                        )
                        assert (
                            remote.post(
                                "/api/plugins" + path,
                                params={"approved_permissions": ["games.read:v1"]},
                                json=source(failure)
                                if scope == "plugins.install"
                                else {"approved_permissions": ["games.read:v1"]},
                            ).status_code
                            == 403
                        )
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
            saved = action("get-config")
            assert (
                saved["master"].get("server_url") is None
                if modern_sync
                else saved["server_url"] == ""
            )
            assert action("status").get("phase") != "complete"
            request("DELETE", f"/{PLUGIN}", 204)
            assert not storage.exists()
            assert not (work / "runtime/.configuration" / f"{PLUGIN}.json").exists()
            assert not request("GET", "")
            print(
                "Revocation/regrant, remote token confinement, confirmed purge and uninstall: passed",
                flush=True,
            )
            checkpoint(
                "revocation/regrant, management-token scope confinement, purge and uninstall"
            )
            report["status"] = "passed"
            (work / "conformance.json").write_text(json.dumps(report, indent=2) + "\n")
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
        try:
            acceptance(
                args.plugins_root.resolve(), args.work_root.resolve(), args.browser
            )
        except Exception as exc:
            path = args.work_root / "conformance.json"
            report = (
                json.loads(path.read_text())
                if path.exists()
                else {"schema_version": 1, "passed": []}
            )
            report.update(status="failed", failure_type=type(exc).__name__)
            path.write_text(json.dumps(report, indent=2) + "\n")
            raise


if __name__ == "__main__":
    main()
