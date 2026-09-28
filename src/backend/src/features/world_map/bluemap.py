# pylint: disable=missing-class-docstring,missing-function-docstring,broad-exception-caught\n"""Renders an uploaded Minecraft world save into a static, browsable web map
using the BlueMap CLI (Java, bundled into the backend image — see
Dockerfile). Verified against the real CLI (v5.23) rather than assumed:

- `java -jar bluemap-cli.jar -c config/ -r`, run with cwd set to a per-world
  work directory, both renders and (as a side effect) writes the browsable
  webapp to `web/` inside that same directory — confirmed live, not from
  docs alone.
- The very first run for a world has no config yet; BlueMap generates the
  default config files itself but exits without rendering (it refuses to
  download Mojang resources until `accept-download` is explicitly true, and
  a fresh map config's `world` path doesn't point anywhere real yet) — so
  the first render is a two-pass "generate defaults, patch them, render for
  real" instead of one call.
- `config/maps/{overworld,nether,end}.conf` each default to `world: "world"`
  (relative) — patched to the real extracted world folder's absolute path.
  `dimension:` already differs per file out of the box, so one world folder
  serves all three.

A game can have several worlds (game_archives.py's GameArchive, kind
"world_save") — everything here is keyed by (game_id, archive_id), a real
stable id rather than a filename, so renaming/re-uploading a version never
changes which render output a world points at.

Rendering a large world can take a long time — callers run this as a
background task, not inline in a request.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import time
import zipfile
from pathlib import Path
from uuid import UUID

from src.features.world_map.thumbnail import generate_world_thumbnail

_BLUEMAP_JAR = Path("/opt/bluemap-cli.jar")

# in-memory, one process — matches this app's scale (single backend
# worker); a restart mid-render just means the user clicks "Render Map"
# again, same as any other interrupted background job here
_render_status: dict[tuple[UUID, UUID], dict] = {}


class WorldMapError(RuntimeError):
    pass


def get_status(game_id: UUID, archive_id: UUID) -> dict:
    return _render_status.get(
        (game_id, archive_id), {"status": "idle", "detail": None, "updated_at": None}
    )


def _set_status(game_id: UUID, archive_id: UUID, status: str, detail: str | None = None) -> None:
    _render_status[(game_id, archive_id)] = {
        "status": status,
        "detail": detail,
        "updated_at": int(time.time()),
    }


def _work_dir(game_dir: Path, archive_id: UUID) -> Path:
    return game_dir / "world_map" / str(archive_id)


def web_root(game_dir: Path, archive_id: UUID) -> Path:
    """Where this world's rendered, browsable map lives once a render
    succeeds."""
    return _work_dir(game_dir, archive_id) / "web"


def thumbnail_path(game_dir: Path, archive_id: UUID) -> Path:
    return _work_dir(game_dir, archive_id) / "thumbnail.png"


async def _run_bluemap(cwd: Path) -> tuple[int, str]:
    cwd.mkdir(parents=True, exist_ok=True)
    process = await asyncio.create_subprocess_exec(
        "java",
        "-jar",
        str(_BLUEMAP_JAR),
        "-c",
        "config/",
        "-r",
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await process.communicate()
    return process.returncode or 0, stdout.decode(errors="replace")


def _patch_config(config_dir: Path, world_dir: Path) -> None:
    core_conf = config_dir / "core.conf"
    if core_conf.is_file():
        text = core_conf.read_text(encoding="utf-8")
        text = re.sub(r"accept-download:\s*false", "accept-download: true", text, count=1)
        core_conf.write_text(text, encoding="utf-8")

    world_path_escaped = str(world_dir.resolve()).replace("\\", "\\\\")
    for map_conf in (config_dir / "maps").glob("*.conf"):
        text = map_conf.read_text(encoding="utf-8")
        text = re.sub(r'world:\s*"world"', f'world: "{world_path_escaped}"', text, count=1)
        map_conf.write_text(text, encoding="utf-8")


def _extract_world(world_zip: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(world_zip) as zf:
        zf.extractall(dest)
    # a zip of the world folder itself (not its contents) extracts to
    # world/<worldname>/level.dat instead of world/level.dat — BlueMap
    # needs the folder that directly contains level.dat, so unwrap one
    # level if that's what happened
    entries = list(dest.iterdir())
    if len(entries) == 1 and entries[0].is_dir() and not (dest / "level.dat").is_file():
        inner = entries[0]
        for item in inner.iterdir():
            shutil.move(str(item), str(dest / item.name))
        inner.rmdir()


async def render_world_map(
    game_id: UUID, archive_id: UUID, game_dir: Path, world_zip: Path
) -> None:
    """Extracts `world_zip` and renders it. Best-effort in the sense that
    any failure is recorded in get_status() rather than raised into
    whatever fire-and-forget background task called this."""
    _set_status(game_id, archive_id, "rendering", "Extracting world save…")
    work_dir = _work_dir(game_dir, archive_id)
    world_dir = work_dir / "world"
    config_dir = work_dir / "config"

    try:
        await asyncio.to_thread(_extract_world, world_zip, world_dir)
    except (OSError, zipfile.BadZipFile) as exc:
        _set_status(game_id, archive_id, "error", f"Could not extract world save: {exc}")
        return

    if not (world_dir / "level.dat").is_file():
        _set_status(
            game_id,
            archive_id,
            "error",
            "That doesn't look like a Minecraft world save (no level.dat found).",
        )
        return

    if not config_dir.is_dir():
        _set_status(game_id, archive_id, "rendering", "Setting up BlueMap (first render only)…")
        await _run_bluemap(work_dir)  # generates default config, expected to exit non-zero here
        if not config_dir.is_dir():
            _set_status(
                game_id,
                archive_id,
                "error",
                "BlueMap did not generate its config: check server logs.",
            )
            return
        _patch_config(config_dir, world_dir)
    else:
        _patch_config(config_dir, world_dir)

    _set_status(
        game_id, archive_id, "rendering", "Rendering map, this can take a while for a large world…"
    )
    code, output = await _run_bluemap(work_dir)
    if code != 0 or not (work_dir / "web" / "index.html").is_file():
        _set_status(game_id, archive_id, "error", f"BlueMap render failed: {output[-500:]}")
        return

    try:
        await asyncio.to_thread(
            generate_world_thumbnail, world_dir, thumbnail_path(game_dir, archive_id)
        )
    except Exception:
        pass  # thumbnail is cosmetic — a failure here shouldn't fail the render

    _set_status(game_id, archive_id, "done", "Map rendered.")
