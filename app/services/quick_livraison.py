from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from sqlmodel import Session

from app.models import Order
from app.services.carriers import run_sync
from app.services.carriers.quick import QuickLivraisonCarrier, _national_phone, _order_amount, _qty
from app.services.catalog import find_product


def _as_order(order_data: dict[str, Any]) -> Any:
    existing = order_data.get("order")
    if existing is not None:
        return existing
    price = order_data.get("price")
    try:
        cents = int(round(float(price) * 100)) if price not in (None, "") else 0
    except (TypeError, ValueError):
        cents = 0
    sku = str(order_data.get("product_code") or order_data.get("sku") or "").strip()
    try:
        qty = int(order_data.get("quantity") or 1)
    except (TypeError, ValueError):
        qty = 1
    phone = str(order_data.get("phone") or "")
    city = str(order_data.get("city") or "").strip()
    return SimpleNamespace(
        full_name=str(order_data.get("client_name") or "Client").strip() or "Client",
        phone=phone,
        phone_national=_national_phone(phone, phone),
        city=city,
        shipping_city=city,
        address=str(order_data.get("address") or "").strip() or city,
        quartier="",
        street="",
        product_slug=sku,
        product_code=sku,
        tier_qty=qty if qty > 0 else 1,
        courier_notes=str(order_data.get("note") or "").strip(),
        total_cents=cents,
        total_price=price,
        id=str(order_data.get("code") or order_data.get("client_order_ref") or ""),
        code=str(order_data.get("code") or order_data.get("client_order_ref") or ""),
    )


def _load_order(db: Session, order_id: str) -> Order | None:
    try:
        uid = UUID(str(order_id))
    except Exception:
        return None
    return db.get(Order, uid)


def _address(order: Order) -> str:
    stored = str(getattr(order, "address", None) or "").strip()
    city = str(getattr(order, "city", "") or "").strip()
    if stored:
        return stored
    bits = [
        str(getattr(order, field, "") or "").strip()
        for field in ("quartier", "street", "building", "landmark")
    ]
    composed = "، ".join(part for part in bits if part)
    return composed or city or "Maroc"


def _quick_id(product: Any) -> int | None:
    raw = getattr(product, "quick_product_id", None) if product is not None else None
    if raw in (None, ""):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _order_code(order: Order) -> str | None:
    custom = str(getattr(order, "code", None) or "").strip()
    if custom:
        return custom
    short = str(order.id).replace("-", "")[:8].upper()
    return short or None


def dispatch_order_from_stock(order_id: str, db: Session) -> dict[str, Any]:
    """Create a Quick Livraison parcel from warehouse stock using the official JSON API."""
    order = _load_order(db, order_id)
    if not order:
        return {"ok": False, "error": "order_not_found", "status_code": 404}

    product = find_product(db, str(order.product_slug or ""))
    quick_product_id = _quick_id(product)
    if not quick_product_id:
        return {"ok": False, "error": "quick_product_id_missing", "status_code": 400}

    carrier = QuickLivraisonCarrier()
    district_id = run_sync(carrier.resolve_mapped_district_id(order, db))
    if not district_id:
        return {"ok": False, "error": "quick_district_not_mapped", "status_code": 400}

    qty = _qty(order)
    phone = _national_phone(
        str(getattr(order, "phone", "") or ""),
        str(getattr(order, "phone_national", "") or ""),
    )
    payload: dict[str, Any] = {
        "district_id": int(district_id),
        "name": str(order.full_name or "").strip() or "Client",
        "phone": phone,
        "address": _address(order),
        "amount": _order_amount(order),
        "note": str(getattr(order, "courier_notes", "") or ""),
        "open": False,
        "received_quantity": {str(int(quick_product_id)): qty},
    }
    code = _order_code(order)
    if code:
        payload["code"] = code

    result = run_sync(carrier.create_stock_delivery(payload, session=db, order=order))
    if not result.get("ok"):
        return result

    tracking = str(result.get("tracking_number") or "").strip()
    if not tracking:
        return {"ok": False, "error": "quick_stock_no_tracking", "status_code": 400}

    now = datetime.now(timezone.utc)
    order.meta_livraison_code = tracking
    order.carrier = "quick_livraison"
    order.carrier_status = "sent_to_carrier"
    order.dispatched_at = now
    if not getattr(order, "meta_livraison_sent_at", None):
        order.meta_livraison_sent_at = now
    ticket = str(result.get("ticket_url") or "").strip() or None
    if ticket:
        order.meta_livraison_ticket_url = ticket
    order.status = "shipped"
    if not order.shipped_at:
        order.shipped_at = now
    if not order.confirmed_at:
        order.confirmed_at = now
    order.updated_at = now
    db.add(order)
    db.commit()
    db.refresh(order)
    return {
        "ok": True,
        "tracking_number": tracking,
        "code_envoi": tracking,
        "ticket_url": ticket or "",
        "carrier": "quick_livraison",
        "quick_product_id": int(quick_product_id),
        "quantity": qty,
        "district_id": int(district_id),
    }


async def create_stock_order(order_data: dict[str, Any]) -> dict[str, Any]:
    """Create a Quick Livraison parcel fulfilled from warehouse stock (official JSON)."""
    carrier = QuickLivraisonCarrier()
    return await carrier.create_stock_order(_as_order(order_data), order_data)
