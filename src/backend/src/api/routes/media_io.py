"""Bringing a media list in from elsewhere and getting it out as a table.

- POST /api/import/mal/preview  what a MyAnimeList export would add or change
- POST /api/import/mal      a MyAnimeList export (XML or gzipped XML) -> anime
- POST /api/import/list[/preview]  a Letterboxd or IMDb export -> movies and TV shows
- POST /api/import/media    the app's own JSON export -> movies, TV shows and anime
- GET  /api/export/media.csv  every movie, show and anime as one CSV

The MAL import never changes a title already on the site (same MAL id, or
same title) unless the user picks that title, so importing twice is harmless."""

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routes.anime import _derive_sort_title
from src.core.app_integrations import get_or_create_app_integration_settings
from src.core.auth import get_current_user
from src.core.integrations import resolve_integrations
from src.database.models.anime import Anime, AnimeSeason
from src.database.models.movies import Movie
from src.database.models.tv_show import TVSeason, TVShow
from src.database.models.user import User
from src.database.session import get_db
from src.features.imports.list_apply import apply_tracking as list_apply_tracking
from src.features.imports.list_apply import differences as list_differences
from src.features.imports.list_apply import fill_details as list_fill_details
from src.features.imports.list_apply import OmdbLookup, match_titles, new_title
from src.features.imports.lists import ImportedTitle, ListImportError, parse_imdb, parse_letterboxd
from src.features.metadata.movies.omdb import OMDBClient
from src.features.metadata.movies.tmdb import TMDBClient
from src.features.imports.mal import MAX_BYTES, MalEntry, MalImportError, parse_mal_export
from src.features.imports.mal_apply import apply_tracking, differences, fill_details, match_entries
from src.features.imports.restore import restore_media
from src.features.imports.yamtrack import build_yamtrack_item, parse_yamtrack

LIST_MAX_BYTES = 30 * 1024 * 1024
router = APIRouter(prefix="/api", tags=["import"], dependencies=[Depends(get_current_user)])

class MalImportResult(BaseModel):
    created: int; updated: int; kept: int; assumed_complete: int; total_in_file: int; details_filled: int; details_not_found: int; details_lookup_failed: int

async def _read_mal(file: UploadFile) -> list[MalEntry]:
    raw = await file.read(MAX_BYTES + 1)
    try: return parse_mal_export(raw)
    except MalImportError as exc: raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

@router.post("/import/mal/preview")
async def preview_mal(file: UploadFile, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    entries = await _read_mal(file); matches = await match_entries(db, current_user.id, entries); new = [m.entry for m in matches if m.existing is None]
    existing = [{"mal_id": m.entry.mal_id, "title": m.entry.title, "site_title": m.existing.title, "differences": differences(m.existing, m.entry)} for m in matches if m.existing is not None]
    return {"total": len(entries), "new_count": len(new), "new_titles": [e.title for e in new[:20]], "existing": [e for e in existing if e["differences"]], "identical": sum(1 for e in existing if not e["differences"])}

@router.post("/import/mal", response_model=MalImportResult)
async def import_mal(file: UploadFile, overwrite: str = Form("[]"), fetch_details: bool = Form(True), db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)) -> MalImportResult:
    try: chosen = {str(x) for x in json.loads(overwrite)}
    except (ValueError, TypeError) as exc: raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="overwrite must be a JSON list.") from exc
    entries = await _read_mal(file); matches = await match_entries(db, current_user.id, entries); created = updated = kept = assumed = 0; touched: list[Anime] = []
    for match in matches:
        entry = match.entry
        if match.existing is not None:
            if entry.mal_id in chosen: apply_tracking(match.existing, entry); touched.append(match.existing); updated += 1; assumed += entry.assumed_complete
            else: touched.append(match.existing); kept += 1
            continue
        show = Anime(user_id=current_user.id, title=entry.title, sort_title=_derive_sort_title(entry.title), external_id=entry.mal_id, source="MyAnimeList import", format=entry.format, status=entry.status, rewatches=entry.rewatches, rating_overall=entry.score, start_date=entry.started, end_date=entry.finished, note=entry.comment, tags=entry.tags, seasons=[AnimeSeason(season_number=1, episode_count=entry.episodes, episodes_watched=entry.watched, status=entry.status)])
        db.add(show); touched.append(show); created += 1; assumed += entry.assumed_complete
    details = {"filled": 0, "not_found": 0, "lookup_failed": 0}
    if fetch_details and touched: details = await fill_details(touched)
    await db.commit(); return MalImportResult(created=created, updated=updated, kept=kept, assumed_complete=assumed, total_in_file=len(entries), details_filled=details["filled"], details_not_found=details["not_found"], details_lookup_failed=details["lookup_failed"])

class ListImportResult(BaseModel):
    created: int; updated: int; kept: int; total_in_file: int; skipped_other: int; details_filled: int; details_not_found: int; details_unavailable: bool; details_source: str | None = None; seasons_assumed_watched: int

def _parse_list(source: str, raw: bytes, filename: str) -> tuple[list[ImportedTitle], int]:
    if len(raw) > LIST_MAX_BYTES: raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="The file is too large.")
    try:
        if source == "letterboxd": return parse_letterboxd(raw, filename), 0
        if source == "imdb": return parse_imdb(raw)
    except ListImportError as exc: raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown source.")

@router.post("/import/list/preview")
async def preview_list(file: UploadFile, source: str = Form(...), db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    items, skipped = _parse_list(source, await file.read(LIST_MAX_BYTES + 1), file.filename or ""); matches = await match_titles(db, current_user.id, items); new = [m.imported for m in matches if m.existing is None]
    existing = [{"mal_id": m.imported.key, "title": m.imported.title, "site_title": m.existing.title, "differences": list_differences(m.existing, m.imported)} for m in matches if m.existing is not None]
    return {"total": len(items), "new_count": len(new), "new_titles": [i.title for i in new[:20]], "existing": [e for e in existing if e["differences"]], "identical": sum(1 for e in existing if not e["differences"]), "skipped_other": skipped}

@router.post("/import/list", response_model=ListImportResult)
async def import_list(file: UploadFile, source: str = Form(...), overwrite: str = Form("[]"), fetch_details: bool = Form(True), db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)) -> ListImportResult:
    try: chosen = {str(x) for x in json.loads(overwrite)}
    except (ValueError, TypeError) as exc: raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="overwrite must be a JSON list.") from exc
    items, skipped = _parse_list(source, await file.read(LIST_MAX_BYTES + 1), file.filename or ""); matches = await match_titles(db, current_user.id, items); created = updated = kept = 0; touched: list[tuple[ImportedTitle, Any, bool]] = []
    for match in matches:
        item = match.imported
        if match.existing is not None:
            picked = item.key in chosen
            if picked: list_apply_tracking(match.existing, item); updated += 1
            else: kept += 1
            touched.append((item, match.existing, picked)); continue
        row = new_title(current_user.id, item); db.add(row); touched.append((item, row, True)); created += 1
    details = {"filled": 0, "not_found": 0, "seasons_assumed_watched": 0}; unavailable = False; details_source: str | None = None
    if fetch_details and touched:
        keys = resolve_integrations(await get_or_create_app_integration_settings(db))
        if keys.tmdb_api_key: details_source = "TMDB"; details = await list_fill_details(TMDBClient(keys.tmdb_api_key), touched)
        elif keys.omdb_api_key: details_source = "OMDb"; details = await list_fill_details(OmdbLookup(OMDBClient(keys.omdb_api_key)), touched)
        else: unavailable = True
    await db.commit(); return ListImportResult(created=created, updated=updated, kept=kept, total_in_file=len(items), skipped_other=skipped, details_filled=details["filled"], details_not_found=details["not_found"], details_unavailable=unavailable, details_source=details_source, seasons_assumed_watched=details["seasons_assumed_watched"])

class YamtrackImportResult(BaseModel):
    created: dict[str, int]; skipped: dict[str, int]; total_rows: int; total_items: int; seasons_created: int; episodes_created: int; errors: list[str]

@router.post("/import/yamtrack", response_model=YamtrackImportResult)
async def import_yamtrack(file: UploadFile, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)) -> YamtrackImportResult:
    raw = await file.read()
    try: groups = parse_yamtrack(raw)
    except ValueError as exc: raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    created = {"movies": 0, "tv_shows": 0, "anime": 0}; skipped = {"movies": 0, "tv_shows": 0, "anime": 0}; errors: list[str] = []; seasons_created = episodes_created = 0
    for group in groups:
        key = {"movie": "movies", "tv": "tv_shows", "anime": "anime"}[group.media_type]
        try:
            item = build_yamtrack_item(group); item.user_id = current_user.id; date_field = "release_date" if group.media_type == "movie" else "first_air_date"; existing = None
            if group.media_type in {"tv", "anime"}:
                model: Any = TVShow if group.media_type == "tv" else Anime
                existing = await db.scalar(select(model).where(model.user_id == current_user.id, model.deleted_at.is_(None), func.lower(model.source) == group.source.lower(), model.external_id == group.media_id))
            if existing is None:
                match_model: Any = Movie if group.media_type == "movie" else TVShow if group.media_type == "tv" else Anime; title = item.title.lower(); release = getattr(item, date_field)
                existing = await db.scalar(select(match_model).where(match_model.user_id == current_user.id, match_model.deleted_at.is_(None), func.lower(match_model.title) == title, getattr(match_model, date_field) == release))
            if existing is not None: skipped[key] += 1; continue
            async with db.begin_nested():
                db.add(item); await db.flush()
                if group.media_type != "movie":
                    seasons = getattr(item, "seasons", []); seasons_created += len(seasons); episodes_created += sum(len(s.episodes) for s in seasons)
                created[key] += 1
        except Exception as exc: skipped[key] += 1; errors.append(f"{(group.parent or {}).get('title', group.media_id)}: {exc}")
    await db.commit(); return YamtrackImportResult(created=created, skipped=skipped, total_rows=sum(1 for _ in csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))), total_items=len(groups), seasons_created=seasons_created, episodes_created=episodes_created, errors=errors[:30])

@router.post("/import/media")
async def import_media(file: UploadFile, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    raw = await file.read(200 * 1024 * 1024 + 1)
    if len(raw) > 200 * 1024 * 1024: raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="The file is too large.")
    try: payload = json.loads(raw)
    except ValueError as exc: raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This is not a JSON file.") from exc
    if isinstance(payload, list) or not isinstance(payload, dict): raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This does not look like a library export (expected an object with movies, tv_shows or anime).")
    if not any(k in payload for k in ("movies", "tv_shows", "anime")): raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This export has no movies, TV shows or anime to restore.")
    return await restore_media(db, current_user.id, payload)

_COLUMNS = ["type", "title", "status", "score", "favorite", "rewatches", "released", "genres", "episodes_watched", "episodes_total", "notes"]
def _row(kind: str, item: Any, released: Any, watched: int | None, total: int | None) -> list[Any]:
    status_value = getattr(item.status, "value", item.status); return [kind, item.title, status_value, "" if item.rating_overall is None else float(item.rating_overall), "yes" if item.favorite else "no", item.rewatches, released.isoformat() if released else "", "; ".join(item.genres or []), "" if watched is None else watched, "" if total is None else total, getattr(item, "note", None) or getattr(item, "notes", None) or ""]
def _safe(cell: Any) -> Any:
    if isinstance(cell, str) and cell[:1] in ("=", "+", "-", "@", "\t", "\r"): return "'" + cell
    return cell

@router.get("/export/media.csv")
async def export_media_csv(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)) -> Response:
    uid = current_user.id
    movies = ((await db.execute(select(Movie).where(Movie.user_id == uid, Movie.deleted_at.is_(None)).order_by(Movie.sort_title))).scalars().all())
    shows = ((await db.execute(select(TVShow).where(TVShow.user_id == uid, TVShow.deleted_at.is_(None)).order_by(TVShow.sort_title))).scalars().all())
    anime = ((await db.execute(select(Anime).where(Anime.user_id == uid, Anime.deleted_at.is_(None)).order_by(Anime.sort_title))).scalars().all())
    async def progress(season_model: Any, show_ids: list[Any]) -> dict[Any, tuple[int, int | None]]:
        if not show_ids: return {}
        rows = (await db.execute(select(season_model.show_id, func.sum(season_model.episodes_watched), func.sum(season_model.episode_count), func.count(season_model.episode_count) == func.count()).where(season_model.show_id.in_(show_ids)).group_by(season_model.show_id))).all()
        return {sid: (int(w or 0), int(t) if t is not None and all_known else None) for sid, w, t, all_known in rows}
    tv_progress = await progress(TVSeason, [s.id for s in shows]); anime_progress = await progress(AnimeSeason, [a.id for a in anime])
    out = io.StringIO(); writer = csv.writer(out); writer.writerow(_COLUMNS)
    for m in movies: writer.writerow([_safe(c) for c in _row("movie", m, m.release_date, None, None)])
    for s in shows:
        w, t = tv_progress.get(s.id, (0, None)); writer.writerow([_safe(c) for c in _row("tv", s, s.first_air_date, w, t)])
    for a in anime:
        w, t = anime_progress.get(a.id, (0, None)); writer.writerow([_safe(c) for c in _row("anime", a, a.first_air_date, w, t)])
    return Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="media-library.csv"'})
