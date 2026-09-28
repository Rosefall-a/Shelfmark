# pylint: disable=too-many-locals
"""Game statistics that need more than a count: playtime spread, the unplayed
pile, cost per hour, backlog hours, achievement completion.

Everything is exact or reported as missing. "No playtime recorded" means the
platform reported none (it is not a claim the game was never played), the
backlog hours only sum games that have a time-to-beat and say how many do
not, and cost per hour only uses games that have both a price and playtime."""

from collections import Counter
from datetime import date, datetime
from statistics import median
from typing import Any

_HOUR = 3600
_BUCKETS = (
    ("Under 1h", 0, 1),
    ("1 to 5h", 1, 5),
    ("5 to 10h", 5, 10),
    ("10 to 25h", 10, 25),
    ("25 to 50h", 25, 50),
    ("50 to 100h", 50, 100),
    ("100h or more", 100, None),
)


def _money(amounts: dict[str, float]) -> list[dict[str, Any]]:
    return [{"currency": k, "amount": round(v, 2)} for k, v in sorted(amounts.items())]


def _seconds_by(games: list[Any], field: str, n: int = 8) -> list[dict[str, Any]]:
    totals: Counter = Counter()
    for g in games:
        name = getattr(g, field)
        if name and g.playtime_seconds:
            totals[name] += g.playtime_seconds
    return [{"name": k, "seconds": v} for k, v in totals.most_common(n)]


def _counted(games: list[Any], field: str, n: int = 8) -> list[dict[str, Any]]:
    counts: Counter = Counter()
    for g in games:
        value = getattr(g, field)
        for name in value if isinstance(value, list) else [value]:
            if name:
                counts[name] += 1
    return [{"name": k, "count": v} for k, v in counts.most_common(n)]


def game_stats(
    games: list[Any],
    achievements: dict[Any, tuple[int, int]],
    now: datetime,
) -> dict[str, Any]:
    """`achievements` maps a game id to (unlocked, total)."""
    owned = [g for g in games if _status(g) != "WISHLIST"]
    played = [g for g in owned if g.playtime_seconds]
    unplayed = [g for g in owned if not g.playtime_seconds]

    unplayed_cost: dict[str, float] = {}
    for g in unplayed:
        if g.purchase_price is not None:
            code = g.purchase_price_currency_code or "?"
            unplayed_cost[code] = unplayed_cost.get(code, 0.0) + float(g.purchase_price)

    buckets = [{"label": "No playtime recorded", "count": len(unplayed)}]
    for label, low, high in _BUCKETS:
        count = sum(
            1
            for g in played
            if g.playtime_seconds >= low * _HOUR
            and (high is None or g.playtime_seconds < high * _HOUR)
        )
        buckets.append({"label": label, "count": count})

    cutoff = now.timestamp() - 30 * 86400
    recent = sorted(
        (g for g in owned if g.last_played_at), key=lambda g: g.last_played_at, reverse=True
    )

    backlog = [g for g in games if _status(g) == "BACKLOG"]
    with_estimate = [g for g in backlog if g.time_to_beat_hours is not None]

    priced: dict[str, list[float]] = {}
    for g in played:
        if g.purchase_price is not None and float(g.purchase_price) > 0:
            code = g.purchase_price_currency_code or "?"
            row = priced.setdefault(code, [0.0, 0.0, 0.0])
            row[0] += float(g.purchase_price)
            row[1] += g.playtime_seconds / _HOUR
            row[2] += 1
    cost_per_hour = [
        {
            "currency": code,
            "per_hour": round(cost / hours, 2),
            "hours": round(hours, 1),
            "games": int(count),
        }
        for code, (cost, hours, count) in sorted(priced.items())
    ]

    progress = []
    fully = 0
    for g in games:
        unlocked, total = achievements.get(g.id, (0, 0))
        if not total:
            continue
        if unlocked == total:
            fully += 1
        else:
            progress.append(
                {"id": str(g.id), "title": g.title, "unlocked": unlocked, "total": total}
            )
    progress.sort(key=lambda r: (r["unlocked"] / r["total"], r["total"]), reverse=True)

    decades: Counter = Counter(
        g.release_date.year // 10 * 10 for g in games if isinstance(g.release_date, date)
    )

    return {
        "owned": len(owned),
        "with_playtime": len(played),
        "unplayed": {"count": len(unplayed), "spent": _money(unplayed_cost)},
        "average_seconds": round(sum(g.playtime_seconds for g in played) / len(played))
        if played
        else None,
        "median_seconds": round(median(g.playtime_seconds for g in played)) if played else None,
        "playtime_buckets": buckets,
        "played_last_30_days": sum(1 for g in recent if g.last_played_at >= cutoff),
        "recently_played": [
            {
                "id": str(g.id),
                "title": g.title,
                "last_played_at": g.last_played_at,
                "seconds": g.playtime_seconds,
            }
            for g in recent[:8]
        ],
        "finished_this_year": sum(
            1
            for g in games
            if g.completion_date and datetime.fromtimestamp(g.completion_date).year == now.year
        ),
        "seconds_by_source": _seconds_by(games, "source"),
        "seconds_by_developer": _seconds_by(games, "developer"),
        "seconds_by_series": _seconds_by(games, "series"),
        "backlog": {
            "count": len(backlog),
            "hours": round(sum(float(g.time_to_beat_hours) for g in with_estimate), 1),
            "without_estimate": len(backlog) - len(with_estimate),
        },
        "cost_per_hour": cost_per_hour,
        "closest_to_full": progress[:8],
        "fully_unlocked": fully,
        "decades": [{"decade": d, "count": c} for d, c in sorted(decades.items())],
        "age_ratings": _counted(owned, "age_rating"),
        "features": _counted(owned, "features"),
    }


def _status(game: Any) -> str:
    return getattr(game.status, "value", str(game.status))
