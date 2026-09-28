# pylint: disable=too-many-locals\n"""Generates a lightweight top-down thumbnail for a Minecraft world save —
deliberately NOT built from BlueMap's own render output. BlueMap's tiles
turn out to be 3D-viewer geometry (JSON meshes for its WebGL client), not
raster images — there is no "grab a tile, that's the thumbnail" shortcut.
Getting an actual rendered-terrain screenshot would mean driving a headless
browser against BlueMap's web viewer, which is a heavy, fragile dependency
(a full Chromium install) for what's meant to be a small card thumbnail.

Instead: read each region file's chunk-location table — the first 4KiB of
every .mca file, a fixed 1024-entry (32x32) offset table that has been part
of the Anvil format since its introduction (MC 1.2) and needs no NBT
parsing or per-version block-palette knowledge at all — to find which
chunks have ever been generated, and render that shape as a simple filled
silhouette. It's an "explored area" map, not a colored terrain render, but
it's genuine, stable, and cheap.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

_REGION_CHUNKS_PER_SIDE = 32
_HEADER_SIZE = 4096
_MAX_THUMBNAIL_PX = 512


def _region_coords(filename: str) -> tuple[int, int] | None:
    # "r.<x>.<z>.mca"
    parts = filename.split(".")
    if len(parts) != 4 or parts[0] != "r" or parts[3] != "mca":
        return None
    try:
        return int(parts[1]), int(parts[2])
    except ValueError:
        return None


def _present_chunks(region_path: Path) -> set[tuple[int, int]]:
    present: set[tuple[int, int]] = set()
    try:
        with region_path.open("rb") as f:
            header = f.read(_HEADER_SIZE)
    except OSError:
        return present
    if len(header) < _HEADER_SIZE:
        return present
    for i in range(1024):
        offset = int.from_bytes(header[i * 4 : i * 4 + 3], "big")
        if offset != 0:
            present.add((i % _REGION_CHUNKS_PER_SIDE, i // _REGION_CHUNKS_PER_SIDE))
    return present


def generate_world_thumbnail(world_dir: Path, output_path: Path) -> bool:
    """world_dir is the extracted world folder (containing level.dat).
    Returns whether a thumbnail was actually produced — a world with no
    readable region files (corrupt upload, wrong folder) just gets no
    thumbnail rather than an error, since this is cosmetic."""
    region_dir = world_dir / "region"
    if not region_dir.is_dir():
        return False

    chunk_points: list[tuple[int, int]] = []
    for region_file in region_dir.glob("r.*.*.mca"):
        coords = _region_coords(region_file.name)
        if coords is None:
            continue
        rx, rz = coords
        for cx, cz in _present_chunks(region_file):
            chunk_points.append(
                (rx * _REGION_CHUNKS_PER_SIDE + cx, rz * _REGION_CHUNKS_PER_SIDE + cz)
            )

    if not chunk_points:
        return False

    xs = [p[0] for p in chunk_points]
    zs = [p[1] for p in chunk_points]
    min_x, max_x = min(xs), max(xs)
    min_z, max_z = min(zs), max(zs)
    width = max(max_x - min_x + 1, 1)
    height = max(max_z - min_z + 1, 1)

    scale = max(1, _MAX_THUMBNAIL_PX // max(width, height))
    img_w, img_h = width * scale, height * scale

    image = Image.new("RGBA", (img_w, img_h), (14, 18, 24, 255))
    land_color = (94, 168, 122, 255)
    for x, z in chunk_points:
        px, pz = (x - min_x) * scale, (z - min_z) * scale
        image.paste(land_color, (px, pz, px + scale, pz + scale))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")
    return True
