"""Real PostgreSQL/host/runtime/browser PWA acceptance with disposable signers.

Use a disposable migrated database and a clean --work-root. No production key is
created. Only catalogue/artifact acquisition uses disposable fixture downloads;
verification, installation, grants, runtime workers and browser routes are real.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from uuid import uuid4

import httpx
from check_plugin_repository_lifecycle import (
    FIXTURE_BASE,
    HOST,
    PASSWORD,
    available_port,
    commit,
    git,
    wait_until,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def acceptance(plugins_root: Path, work: Path) -> None:
    work.mkdir(parents=True, exist_ok=False)
    root = work / "release-source"
    root.mkdir()
    for folder in ("tools", "sdk", "publishers", "official"):
        shutil.copytree(
            plugins_root / folder, root / folder, ignore=shutil.ignore_patterns("__pycache__")
        )
    shutil.copyfile(plugins_root / ".gitignore", root / ".gitignore")
    (root / "catalogue.json").write_text(
        json.dumps({"name": "PWA acceptance", "base_url": FIXTURE_BASE})
    )
    key = Ed25519PrivateKey.generate()
    encoded = base64.b64encode(key.public_key().public_bytes_raw()).decode()
    record = {
        "key_id": "pwa-acceptance",
        "publisher": "Unnamed Tracking Official",
        "channel": "official",
        "public_key_file": "pwa-acceptance.public-key.b64",
        "public_key_b64": encoded,
        "public_key_sha256": hashlib.sha256(key.public_key().public_bytes_raw()).hexdigest(),
        "status": "active",
        "plugin_id_prefixes": ["official.pwa"],
    }
    registry = {"schema_version": 1, "publishers": [record]}
    (root / "publishers/pwa-acceptance.public-key.b64").write_text(encoded)
    (root / "publishers/registry.json").write_text(json.dumps(registry))
    (work / "trusted.json").write_text(json.dumps(registry))
    git(root, "init")
    git(root, "config", "user.name", "PWA acceptance")
    git(root, "config", "user.email", "pwa@example.invalid")
    commit(root, "feat: prepare disposable PWA acceptance")
    signing = {
        **os.environ,
        "PLUGIN_OFFICIAL_SIGNING_KEY_ID": "pwa-acceptance",
        "PLUGIN_OFFICIAL_SIGNING_KEY_B64": base64.b64encode(key.private_bytes_raw()).decode(),
        "PLUGIN_SIGNING_FALLBACK": "unsigned",
    }
    for version in ("0.0.1", "0.0.2", "0.0.3"):
        path = root / "official/pwa/manifest.json"
        manifest = json.loads(path.read_text())
        manifest["version"] = version
        path.write_text(json.dumps(manifest))
        version_data = json.dumps({"version": version}).encode()
        (root / "official/pwa/pwa/version.json").write_bytes(version_data)
        provenance_path = root / "official/pwa/pwa/provenance.json"
        provenance = json.loads(provenance_path.read_text())
        provenance["version"] = version
        provenance["sha256"]["version.json"] = hashlib.sha256(version_data).hexdigest()
        provenance_path.write_text(json.dumps(provenance))
        if version == "0.0.3":
            (root / "official/pwa/plugin.py").write_text(
                'def main():\n    raise RuntimeError("acceptance failed startup")\n'
            )
        commit(root, f"fix: prepare PWA {version}")
        subprocess.run(
            [sys.executable, str(root / "tools/build_packages.py"), "--publish"],
            env=signing,
            check=True,
        )
        commit(root, "chore: retain immutable acceptance packages")
        if version != "0.0.3":
            shutil.copyfile(root / "list.json", work / f"catalogue-{version}.json")
    shutil.copyfile(work / "catalogue-0.0.1.json", root / "list.json")
    first = root / "dist/official.pwa-0.0.1.utp"
    with zipfile.ZipFile(first) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    for kind in ("unsigned", "invalid"):
        manifest = json.loads(entries["manifest.json"])
        manifest["integrity"]["signature"] = (
            None if kind == "unsigned" else "v2:" + base64.b64encode(b"x" * 64).decode()
        )
        if kind == "unsigned":
            manifest["integrity"]["key_id"] = None
        with zipfile.ZipFile(work / f"{kind}.utp", "w") as archive:
            for name, content in entries.items():
                archive.writestr(name, json.dumps(manifest) if name == "manifest.json" else content)
    host_port, runtime_port = available_port(), available_port()
    env = {
        **os.environ,
        "PRIMARY_USER_USERNAME": "pwa-" + uuid4().hex,
        "PRIMARY_USER_EMAIL": uuid4().hex + "@example.invalid",
        "PRIMARY_USER_PASSWORD": PASSWORD,
        "PLUGIN_RUNTIME_URL": f"http://127.0.0.1:{runtime_port}",
        "PLUGIN_RUNTIME_TOKEN": uuid4().hex + uuid4().hex,
        "PLUGIN_GATEWAY_URL": f"http://127.0.0.1:{host_port}",
        "PLUGIN_MANAGER_STATE_PATH": str(work / "manager.json"),
        "PLUGIN_CATALOGUE_REGISTRY": str(work / "catalogues.json"),
        "PLUGIN_TRUSTED_PUBLISHER_REGISTRY": str(work / "trusted.json"),
        "NONBUBBLE_ENV": "true",
        "STARTUP_MODE": "testing",
        "DEBUG": "false",
        "PWA_ACCEPTANCE_ROOT": str(root),
        "PWA_ACCEPTANCE_WORK": str(work),
        "INTEGRATION_WORK_ROOT": str(work),
        "PWA_ACCEPTANCE_PYTHON": sys.executable,
    }
    processes, logs = [], []
    try:
        for mode, port in (("runtime", runtime_port), ("host", host_port)):
            log = (work / f"{mode}.log").open("w")
            logs.append(log)
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        str(HOST / "tools/check_plugin_repository_lifecycle.py"),
                        "--mode",
                        mode,
                        "--work-root",
                        str(work),
                        "--port",
                        str(port),
                    ],
                    env=env,
                    cwd=HOST / "src/backend",
                    stdout=log,
                    stderr=log,
                )
            )
        wait_until(lambda: httpx.get(env["PLUGIN_GATEWAY_URL"] + "/health").status_code == 200)
        subprocess.run(
            ["node", str(HOST / "tools/check_pwa_browser.mjs"), str(plugins_root)],
            env=env,
            check=True,
        )
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log in logs:
            log.close()


async def expire_session() -> None:
    """Expire only the explicitly created acceptance account in its test DB."""
    username = os.environ["PRIMARY_USER_USERNAME"]
    if not username.startswith("pwa-") or not os.getenv("PWA_ACCEPTANCE_WORK"):
        raise RuntimeError("Session expiry is restricted to disposable PWA acceptance")
    sys.path.insert(0, str(HOST / "src/backend"))
    from sqlalchemy import select, update
    from src.database.models.auth import UserSession
    from src.database.models.user import User
    from src.database.session import SessionLocal
    from src.main import app  # noqa: F401 - initialize all mapped models

    async with SessionLocal() as db:
        user_id = await db.scalar(select(User.id).where(User.username == username))
        if user_id is None:
            raise RuntimeError("Acceptance user not found")
        await db.execute(
            update(UserSession)
            .where(UserSession.user_id == user_id)
            .values(expires_at=int(time.time()) - 60)
        )
        await db.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugins-root", type=Path)
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--expire-session", action="store_true")
    args = parser.parse_args()
    if args.expire_session:
        asyncio.run(expire_session())
    else:
        if args.plugins_root is None or args.work_root is None:
            parser.error("--plugins-root and --work-root are required")
        acceptance(args.plugins_root.resolve(), args.work_root.resolve())
