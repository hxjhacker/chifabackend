from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlmodel import Session, select

from app.db import engine
from app.models import Order
from app.services.carriers import get_carrier, normalize_carrier
from app.services.carriers.quick import is_dummy_parcel_code, quick_client_code

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
    order.carrier_status = next_status
    if next_status in ("shipped", "delivered", "returned") and not getattr(order, "shipped_at", None):
        order.shipped_at = now
    if next_status == "delivered":
        if not getattr(order, "delivered_at", None):
            order.delivered_at = now
        order.cancelled_at = None
        if hasattr(order, "payment_status"):
            setattr(order, "payment_status", "paid")
    elif next_status == "cancelled":
        if not getattr(order, "cancelled_at", None):
            order.cancelled_at = now
    elif next_status == "returned":
        order.delivered_at = None
        order.cancelled_at = None
    elif next_status == "shipped":
        order.delivered_at = None
        order.cancelled_at = None


def _cfg_reference(order: Order) -> str:
    return quick_client_code(order)


def _load_sync_jobs() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    with Session(engine) as session:
        rows = session.exec(select(Order).where(Order.status.in_(("shipped", "in_shipping")))).all()
        tracked = [order for order in rows if str(getattr(order, "meta_livraison_code", "") or "").strip()]
        for order in tracked[:MAX_SYNC]:
            stored = str(order.meta_livraison_code or "").strip()
            current = str(order.status or "")
            if current == "in_shipping":
                current = "shipped"
            carrier = normalize_carrier(getattr(order, "carrier", None))
            cfg = _cfg_reference(order)
            if carrier == "quick_livraison":
                query_code = cfg or stored
                extras = []
                if stored and stored != query_code and not is_dummy_parcel_code(stored):
                    extras.append(stored)
            else:
                query_code = stored
                extras = [cfg] if cfg and cfg != stored else []
            jobs.append(
                {
                    "order_id": str(order.id),
                    "tracking": query_code,
                    "stored_tracking": stored,
                    "rewrite_tracking": cfg if carrier == "quick_livraison" and is_dummy_parcel_code(stored) and cfg else "",
                    "carrier": carrier,
                    "from_status": current,
                    "extra_codes": extras,
                }
            )
    return jobs


def _persist_status_updates(updates: list[tuple[str, str]], tracking_rewrites: list[tuple[str, str]] | None = None) -> None:
    if not updates and not tracking_rewrites:
        return
    rewrites = {order_id: code for order_id, code in (tracking_rewrites or []) if order_id and code}
    with Session(engine) as session:
        seen: set[str] = set()
        for order_id, db_status in updates:
            seen.add(order_id)
            try:
                order = session.get(Order, UUID(order_id))
            except Exception:
                order = session.get(Order, order_id)
            if not order:
                continue
            _apply_status(order, db_status)
            new_code = rewrites.get(order_id)
            if new_code:
                order.meta_livraison_code = new_code[:80]
            session.add(order)
        for order_id, new_code in rewrites.items():
            if order_id in seen:
                continue
            try:
                order = session.get(Order, UUID(order_id))
            except Exception:
                order = session.get(Order, order_id)
            if not order:
                continue
            order.meta_livraison_code = new_code[:80]
            order.updated_at = datetime.now(timezone.utc)
            session.add(order)
        session.commit()


async def sync_shipped_orders_async() -> dict[str, Any]:
    details: list[dict[str, Any]] = []
    updates: list[tuple[str, str]] = []
    tracking_rewrites: list[tuple[str, str]] = []
    jobs = _load_sync_jobs()
    for job in jobs:
        carrier_id = str(job["carrier"])
        code = str(job["tracking"])
        rewrite = str(job.get("rewrite_tracking") or "").strip()
        if rewrite:
            tracking_rewrites.append((str(job["order_id"]), rewrite))
        adapter = get_carrier(carrier_id)
        if not adapter.is_configured():
            details.append(
                {
                    "order_id": job["order_id"],
                    "tracking": code,
                    "carrier": carrier_id,
                    "from_status": job["from_status"],
                    "to_status": job["from_status"],
                    "updated": False,
                    "error": f"{carrier_id}_not_configured",
                }
            )
            continue
        try:
            result = await adapter.get_tracking_status(code, extra_codes=job["extra_codes"])
        except Exception as exc:
            details.append(
                {
                    "order_id": job["order_id"],
                    "tracking": code,
                    "carrier": carrier_id,
                    "from_status": job["from_status"],
                    "to_status": job["from_status"],
                    "updated": False,
                    "error": str(exc) or "tracking_failed",
                }
            )
            continue
        public = str(result.get("status") or "") if result.get("ok") else ""
        db_status = PUBLIC_TO_DB.get(public)
        current = str(job["from_status"])
        item = {
            "order_id": job["order_id"],
            "tracking": rewrite or code,
            "lookup_code": result.get("lookup_code") or code,
            "carrier": carrier_id,
            "from_status": current,
            "to_status": db_status or current,
            "meta_status": result.get("raw") or public,
            "updated": False,
            "error": result.get("error") or "",
        }
        if not result.get("ok") or not db_status or db_status == current:
            details.append(item)
            continue
        updates.append((str(job["order_id"]), db_status))
        item["updated"] = True
        item["to_status"] = db_status
        details.append(item)
    _persist_status_updates(updates, tracking_rewrites)
    return {"total_checked": len(details), "updated_count": len(updates), "details": details}


def sync_shipped_orders(
    *,
    api_key: str | None = None,
    api_secret: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    _ = (api_key, api_secret, base_url)
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(sync_shipped_orders_async())
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, sync_shipped_orders_async()).result()


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
