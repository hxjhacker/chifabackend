from __future__ import annotations

import json

from sqlalchemy import text
from sqlmodel import Session

from app.config import settings

PACK_NAMES = {
    "quran": "USB القرآن الكريم",
    "kids": "USB تعليم الأطفال",
    "music": "USB الأغاني والموسيقى",
    "educative": "الفلاشة التعليمية الذكية",
}


def notify_new_order(
    session: Session,
    *,
    full_name: str,
    city: str,
    product_slug: str,
    qty: int = 1,
    total_mad: float = 0,
) -> None:
    if not settings.vapid_private_key or not settings.vapid_public_key:
        return
    try:
        from pywebpush import WebPushException, webpush
    except Exception:
        return

    product = PACK_NAMES.get(product_slug, product_slug)
    qty_bit = f" × {qty}" if qty and qty > 1 else ""
    total_bit = f" · {int(round(total_mad))} DH" if total_mad else ""
    payload = json.dumps(
        {
            "title": "طلب جديد في المتجر! 🔔",
            "body": f"{full_name} · {city} · {product}{qty_bit}{total_bit}",
            "url": "/mydashboard",
            "tag": "chifaglow-new-order",
        },
        ensure_ascii=False,
    )
    try:
        rows = session.execute(text("SELECT endpoint, p256dh, auth FROM push_subscriptions")).mappings().all()
    except Exception:
        session.rollback()
        return

    stale: list[str] = []
    for row in rows:
        try:
            webpush(
                subscription_info={
                    "endpoint": row["endpoint"],
                    "keys": {"p256dh": row["p256dh"], "auth": row["auth"]},
                },
                data=payload,
                vapid_private_key=settings.vapid_private_key,
                vapid_claims={"sub": settings.vapid_subject},
                ttl=3600,
            )
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                stale.append(str(row["endpoint"]))
        except Exception:
            continue
    for endpoint in stale:
        try:
            session.execute(text("DELETE FROM push_subscriptions WHERE endpoint = :endpoint"), {"endpoint": endpoint})
        except Exception:
            continue
    if stale:
        try:
            session.commit()
        except Exception:
            session.rollback()
