from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from app.db import engine
from app.models import Order
from app.services.carriers import get_carrier, normalize_carrier, run_sync

MAX_SYNC = 200
PUBLIC_TO_DB = {
    "delivered": "delivered",
    "returned": "returned",
    "cancelled": "cancelled",
    "in_shipping": "shipped",
}


def _apply_status(order: Order, next_status: str) -> None:
    now = datetime.now(timezone.utc)
    order.status = next_status
    order.updated_at = now
    if next_status in ("shipped", "delivered", "returned") and not getattr(order, "shipped_at", None):
        order.shipped_at = now
    if next_status == "delivered":
        if not getattr(order, "delivered_at", None):
            order.delivered_at = now
        order.cancelled_at = None
    elif next_status == "cancelled":
        if not getattr(order, "cancelled_at", None):
            order.cancelled_at = now
    elif next_status == "returned":
        order.delivered_at = None
        order.cancelled_at = None
    elif next_status == "shipped":
        order.delivered_at = None
        order.cancelled_at = None


def sync_shipped_orders(
    *,
    api_key: str | None = None,
    api_secret: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    _ = (api_key, api_secret, base_url)
    details: list[dict[str, Any]] = []
    updated = 0
    with Session(engine) as session:
        rows = session.exec(select(Order).where(Order.status.in_(("shipped", "in_shipping")))).all()
        tracked = [order for order in rows if str(getattr(order, "meta_livraison_code", "") or "").strip()]
        tracked = tracked[:MAX_SYNC]
        for order in tracked:
            code = str(order.meta_livraison_code or "").strip()
            carrier_id = normalize_carrier(getattr(order, "carrier", None))
            adapter = get_carrier(carrier_id)
            if not adapter.is_configured():
                details.append(
                    {
                        "order_id": str(order.id),
                        "tracking": code,
                        "carrier": carrier_id,
                        "from_status": str(order.status or ""),
                        "to_status": str(order.status or ""),
                        "updated": False,
                        "error": f"{carrier_id}_not_configured",
                    }
                )
                continue
            result = run_sync(adapter.get_tracking_status(code))
            public = str(result.get("status") or "") if result.get("ok") else ""
            db_status = PUBLIC_TO_DB.get(public)
            current = str(order.status or "")
            if current == "in_shipping":
                current = "shipped"
            item = {
                "order_id": str(order.id),
                "tracking": code,
                "carrier": carrier_id,
                "from_status": current,
                "to_status": db_status or current,
                "meta_status": result.get("raw") or public,
                "updated": False,
                "error": result.get("error") or "",
            }
            if not result.get("ok") or not db_status:
                details.append(item)
                continue
            if db_status == current:
                details.append(item)
                continue
            _apply_status(order, db_status)
            session.add(order)
            item["updated"] = True
            item["to_status"] = db_status
            updated += 1
            details.append(item)
        session.commit()
    return {"total_checked": len(details), "updated_count": updated, "details": details}


def run_scheduled_tracking_sync() -> None:
    try:
        report = sync_shipped_orders()
        print(
            f"[CARRIER_TRACKING_SYNC] checked={report.get('total_checked')} "
            f"updated={report.get('updated_count')} error={report.get('error') or ''}",
            flush=True,
        )
    except Exception as exc:
        print(f"[CARRIER_TRACKING_SYNC] failed: {exc}", flush=True)
