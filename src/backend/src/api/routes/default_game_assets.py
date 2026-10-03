# pylint: disable=line-too-long
"""Fallback artwork for games that do not have stored cover art."""

import hashlib
from html import escape
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routes.games import _DATA_ROOT, ALLOWED_ASSET_KINDS, _get_game_or_404
from src.core.auth import get_current_user
from src.database.models.user import User
from src.database.session import get_db
from src.helpers.save_game_asset import ASSET_FILENAMES, AssetKind

router = APIRouter(
    prefix="/api/game",
    tags=["game"],
    dependencies=[Depends(get_current_user)],
)


def _cover_palette(game_id: UUID) -> tuple[str, str, str]:
    """Pick a stable palette so a game's fallback cover does not change."""
    digest = hashlib.sha256(str(game_id).encode("utf-8")).hexdigest()
    palettes = (
        ("#16132a", "#3d2a68", "#9b87f5"),
        ("#102326", "#1f5960", "#65d6c7"),
        ("#26151b", "#633044", "#ef8aa8"),
        ("#201a12", "#66502b", "#e3bd69"),
        ("#151c2b", "#294a78", "#76a8ee"),
        ("#1b1722", "#4d315e", "#cf8fe8"),
    )
    index = int(digest[:8], 16) % len(palettes)
    return palettes[index]


def _default_cover_svg(game_id: UUID, title: str) -> str:
    """Build a lightweight, title-aware SVG fallback cover."""
    background, foreground, accent = _cover_palette(game_id)
    safe_title = escape(title.strip() or "Unknown Game")
    digest = hashlib.sha256(str(game_id).encode("utf-8")).hexdigest()
    x1 = 20 + int(digest[8:12], 16) % 60
    y1 = 20 + int(digest[12:16], 16) % 55
    x2 = 35 + int(digest[16:20], 16) % 55
    y2 = 40 + int(digest[20:24], 16) % 45

    return f"""<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 600 900\" role=\"img\" aria-label=\"{safe_title} default cover\">
  <defs>
    <linearGradient id=\"bg\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\">
      <stop offset=\"0\" stop-color=\"{background}\"/>
      <stop offset=\"1\" stop-color=\"{foreground}\"/>
    </linearGradient>
    <radialGradient id=\"glow\" cx=\"{x1}%\" cy=\"{y1}%\" r=\"70%\">
      <stop offset=\"0\" stop-color=\"{accent}\" stop-opacity=\".38\"/>
      <stop offset=\"1\" stop-color=\"{accent}\" stop-opacity=\"0\"/>
    </radialGradient>
    <filter id=\"blur\"><feGaussianBlur stdDeviation=\"42\"/></filter>
  </defs>
  <rect width=\"600\" height=\"900\" fill=\"url(#bg)\"/>
  <circle cx=\"{x1 * 6}\" cy=\"{y1 * 9}\" r=\"250\" fill=\"url(#glow)\" filter=\"url(#blur)\"/>
  <circle cx=\"{x2 * 6}\" cy=\"{y2 * 9}\" r=\"180\" fill=\"{accent}\" opacity=\".09\"/>
  <path d=\"M0 650 C140 570 260 760 600 600 V900 H0Z\" fill=\"#000\" opacity=\".22\"/>
  <g transform=\"translate(300 330)\" fill=\"none\" stroke=\"{accent}\" stroke-width=\"10\" stroke-linecap=\"round\" stroke-linejoin=\"round\" opacity=\".9\">
    <path d=\"M-112 8 L-84 -48 H-32 L-16 -70 H16 L32 -48 H84 L112 8 L90 62 H52 L26 20 H-26 L-52 62 H-90 Z\"/>
    <path d=\"M-67 -10 V26 M-85 8 H-49\"/>
    <circle cx=\"62\" cy=\"-5\" r=\"7\" fill=\"{accent}\" stroke=\"none\"/>
    <circle cx=\"84\" cy=\"17\" r=\"7\" fill=\"{accent}\" stroke=\"none\"/>
  </g>
  <rect x=\"54\" y=\"650\" width=\"492\" height=\"2\" fill=\"{accent}\" opacity=\".45\"/>
  <text x=\"54\" y=\"705\" fill=\"#fff\" font-family=\"system-ui, -apple-system, Segoe UI, sans-serif\" font-size=\"42\" font-weight=\"700\">{safe_title}</text>
  <text x=\"54\" y=\"750\" fill=\"#fff\" opacity=\".55\" font-family=\"system-ui, -apple-system, Segoe UI, sans-serif\" font-size=\"16\" letter-spacing=\"3\">NO COVER ART</text>
</svg>"""


@router.get("/{game_id}/assets/{asset_kind}")
async def get_game_asset_with_fallback(
    game_id: UUID,
    asset_kind: AssetKind,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Serve stored artwork, falling back to generated cover art when needed."""
    if asset_kind not in ALLOWED_ASSET_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported asset kind '{asset_kind}'. Supported values: {sorted(ALLOWED_ASSET_KINDS)}",
        )

    game = await _get_game_or_404(game_id, db, current_user.id)
    asset_path = (
        _DATA_ROOT
        / str(game.user_id)
        / "games"
        / game.folder_location
        / ASSET_FILENAMES[asset_kind]
    )

    if asset_path.is_file():
        return FileResponse(
            asset_path,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=3600, must-revalidate"},
        )

    if asset_kind != "key_art":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset '{asset_kind}' has not been uploaded for game {game_id}.",
        )

    return Response(
        content=_default_cover_svg(game.id, game.title),
        media_type="image/svg+xml",
        headers={"Cache-Control": "private, max-age=3600, must-revalidate"},
    )
