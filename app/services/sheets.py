from __future__ import annotations

import json
from datetime import timezone

import httpx
from sqlmodel import Session, select

from app.config import settings
from app.models import Order, Product
from app.services.pricing import cents_to_mad


def product_name_ar(session: Session, slug: str) -> str:
    product = session.exec(select(Product).where(Product.slug == slug)).first()
    return product.name_ar if product else slug


def order_sheet_payload(order: Order, product_name: str) -> dict:
    items = [
        {
            "slug": item.product_slug,
            "role": item.role,
            "qty": item.quantity,
            "line_total": cents_to_mad(item.line_total_cents),
        }
        for item in (order.items or [])
    ]
    created = order.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return {
        "order_id": str(order.id),
        "created_at": created.isoformat(),
        "full_name": order.full_name,
        "phone": order.phone,
        "city": order.city,
        "product_slug": order.product_slug,
        "product_name": product_name,
        "tier_qty": order.tier_qty,
        "tier_price": cents_to_mad(order.tier_price_cents),
        "cross_sell_slug": order.cross_sell_slug or "",
        "cross_sell_price": cents_to_mad(order.cross_sell_price_cents) if order.cross_sell_price_cents else "",
        "upsell_slug": order.upsell_slug or "",
        "upsell_price": cents_to_mad(order.upsell_price_cents) if order.upsell_price_cents else "",
        "subtotal": cents_to_mad(order.subtotal_cents),
        "total": cents_to_mad(order.total_cents),
        "currency": order.currency,
        "status": order.status,
        "payment_method": order.payment_method,
        "event_id": order.event_id,
        "landing_url": order.landing_url or "",
        "source": order.source,
        "items_json": json.dumps(items, ensure_ascii=False),
    }


async def push_order_to_sheets(order: Order, product_name: str) -> None:
    url = (settings.google_sheets_webhook_url or "").strip()
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            await client.post(url, json=order_sheet_payload(order, product_name))
    except httpx.HTTPError:
        return


push_order_to_sheets = push_order_to_sheets
