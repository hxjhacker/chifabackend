from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlmodel import Session

from app.models import PageView

CASABLANCA = ZoneInfo("Africa/Casablanca")
PRODUCTS = ("quran", "kids", "music")
MONTHS_AR = (
    "يناير",
    "فبراير",
    "مارس",
    "أبريل",
    "ماي",
    "يونيو",
    "يوليو",
    "غشت",
    "شتنبر",
    "أكتوبر",
    "نونبر",
    "دجنبر",
)


def normalize_slug(slug: str | None) -> str | None:
    raw = (slug or "").strip().lower()
    if raw == "educative":
        return "kids"
    if raw in PRODUCTS:
        return raw
    return None


def record_page_view(session: Session, kind: str, product_slug: str | None = None, path: str | None = None) -> bool:
    slug = normalize_slug(product_slug) if kind == "product" else None
    if kind == "product" and not slug:
        return False
    if kind not in ("store", "product"):
        return False
    session.add(
        PageView(
            id=uuid4(),
            kind=kind,
            product_slug=slug,
            path=(path or "")[:400] or None,
        )
    )
    session.commit()
    return True


def _today() -> date:
    return datetime.now(CASABLANCA).date()


def _range_window(range_name: str, custom_date: str | None) -> tuple[date, date, str, str]:
    today = _today()
    if range_name == "custom" and custom_date:
        try:
            start = date.fromisoformat(custom_date)
            return start, start + timedelta(days=1), "hour", "custom"
        except ValueError:
            pass
    if range_name == "week":
        return today - timedelta(days=6), today + timedelta(days=1), "day", "week"
    if range_name == "month":
        start = today.replace(day=1)
        end = date(today.year + 1, 1, 1) if today.month == 12 else date(today.year, today.month + 1, 1)
        return start, end, "day", "month"
    return today, today + timedelta(days=1), "hour", "today"


def _iter_days(start: date, end: date):
    cursor = start
    while cursor < end:
        yield cursor
        cursor += timedelta(days=1)


def _ar_day(value: date) -> str:
    return f"{value.day} {MONTHS_AR[value.month - 1]}"


def _empty_totals() -> dict[str, int]:
    return {"all": 0, "store": 0, "quran": 0, "kids": 0, "music": 0}


def _count_range(session: Session, start: date, end: date) -> dict[str, int]:
    totals = _empty_totals()
    rows = session.execute(
        text(
            """
            SELECT kind, product_slug, COUNT(*)::int AS n
            FROM page_views
            WHERE created_at >= (CAST(:start AS date) AT TIME ZONE 'Africa/Casablanca')
              AND created_at < (CAST(:end AS date) AT TIME ZONE 'Africa/Casablanca')
            GROUP BY kind, product_slug
            """
        ),
        {"start": start.isoformat(), "end": end.isoformat()},
    )
    for row in rows.mappings():
        n = int(row["n"] or 0)
        totals["all"] += n
        if row["kind"] == "store":
            totals["store"] += n
        slug = normalize_slug(row["product_slug"])
        if slug:
            totals[slug] += n
    return totals


def observatory_stats(session: Session, range_name: str, custom_date: str | None = None) -> dict:
    start, end, bucket, resolved = _range_window(range_name, custom_date)
    if bucket == "hour":
        labels = [f"{hour:02d}:00" for hour in range(24)]
        keys = [f"{hour:02d}" for hour in range(24)]
    else:
        days = list(_iter_days(start, end))
        labels = [_ar_day(day) for day in days]
        keys = [day.isoformat() for day in days]

    series = {
        "labels": labels,
        "quran": [0] * len(labels),
        "kids": [0] * len(labels),
        "music": [0] * len(labels),
    }
    payload = {
        "range": resolved,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "totals": _empty_totals(),
        "trend_pct": 0,
        "series": series,
    }

    try:
        payload["totals"] = _count_range(session, start, end)
        span = max(1, (end - start).days)
        previous = _count_range(session, start - timedelta(days=span), start)
        if previous["all"] > 0:
            payload["trend_pct"] = round(((payload["totals"]["all"] - previous["all"]) / previous["all"]) * 100)
        elif payload["totals"]["all"] > 0:
            payload["trend_pct"] = 100
        else:
            payload["trend_pct"] = 0

        trunc = "hour" if bucket == "hour" else "day"
        fmt = "HH24" if bucket == "hour" else "YYYY-MM-DD"
        rows = session.execute(
            text(
                f"""
                SELECT to_char(date_trunc('{trunc}', created_at AT TIME ZONE 'Africa/Casablanca'), '{fmt}') AS bucket,
                       product_slug,
                       COUNT(*)::int AS n
                FROM page_views
                WHERE kind = 'product'
                  AND created_at >= (CAST(:start AS date) AT TIME ZONE 'Africa/Casablanca')
                  AND created_at < (CAST(:end AS date) AT TIME ZONE 'Africa/Casablanca')
                GROUP BY 1, 2
                """
            ),
            {"start": start.isoformat(), "end": end.isoformat()},
        )
        index = {key: i for i, key in enumerate(keys)}
        for row in rows.mappings():
            slug = normalize_slug(row["product_slug"])
            if not slug:
                continue
            key = str(row["bucket"]).zfill(2) if bucket == "hour" else str(row["bucket"])
            i = index.get(key)
            if i is None:
                continue
            series[slug][i] += int(row["n"] or 0)
    except Exception:
        session.rollback()

    return payload
