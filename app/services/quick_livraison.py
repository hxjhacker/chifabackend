from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.services.carriers.quick import QuickLivraisonCarrier, _national_phone


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


async def create_stock_order(order_data: dict[str, Any]) -> dict[str, Any]:
    """Create a Quick Livraison parcel fulfilled from warehouse stock (ramassage stock)."""
    carrier = QuickLivraisonCarrier()
    return await carrier.create_stock_order(_as_order(order_data), order_data)
