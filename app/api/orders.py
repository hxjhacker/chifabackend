from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request
from sqlmodel import Session, select

from app.db import get_session
from app.dependencies import get_current_admin
from app.models import Order, OrderItem, Product
from app.schemas import OrderCreate, UpsellCreate
from app.services.capi import purchase_event_id, send_purchase
from app.services.fraud import ip_is_blocked
from app.services.phone import normalize_ma_phone, to_national
from app.services.pricing import (
    CROSS_SELL_CENTS,
    PRODUCT_SLUGS,
    UPSELL_CENTS,
    canonical_product_slug,
    cents_to_mad,
    compute_subtotal,
    tier_prices_for,
)
from app.services.push import notify_new_order
from app.services.sheets import product_name_ar, push_order_to_sheets

router = APIRouter(prefix="/api")


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _serialize(order: Order) -> dict:
    return {
        "order_id": str(order.id),
        "status": order.status,
        "full_name": order.full_name,
        "phone_national": order.phone_national,
        "city": order.city,
        "product_slug": order.product_slug,
        "tier_qty": order.tier_qty,
        "cross_sell_slug": order.cross_sell_slug,
        "upsell_slug": order.upsell_slug,
        "subtotal": cents_to_mad(order.subtotal_cents),
        "total": cents_to_mad(order.total_cents),
        "currency": order.currency,
        "payment_method": order.payment_method,
        "items": [
            {
                "product_slug": i.product_slug,
                "role": i.role,
                "quantity": i.quantity,
                "line_total": cents_to_mad(i.line_total_cents),
            }
            for i in (order.items or [])
        ],
        "upsell_offer": {
            "price": 99,
            "candidates": [s for s in PRODUCT_SLUGS if s not in {order.product_slug, order.cross_sell_slug}],
        },
        "purchase_event_id": purchase_event_id(order.id),
    }


def _queue_side_effects(
    background: BackgroundTasks, order: Order, product_name: str, *, send_capi: bool = True
) -> None:
    if send_capi:
        background.add_task(send_purchase, order, purchase_event_id(order.id))
    background.add_task(push_order_to_sheets, order, product_name)
    background.add_task(
        _notify_order,
        str(order.full_name),
        str(order.city),
        str(order.product_slug),
        int(order.tier_qty or 1),
        cents_to_mad(order.total_cents),
    )


def _notify_order(full_name: str, city: str, product_slug: str, qty: int, total_mad: float) -> None:
    from sqlmodel import Session

    from app.db import engine

    with Session(engine) as session:
        notify_new_order(
            session,
            full_name=full_name,
            city=city,
            product_slug=product_slug,
            qty=qty,
            total_mad=total_mad,
        )


@router.post("/orders", status_code=201)
def create_order(
    payload: OrderCreate,
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    try:
        e164 = normalize_ma_phone(payload.phone)
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_ma_phone")

    customer_city_raw = payload.city.strip()
    if len(customer_city_raw) < 2:
        raise HTTPException(status_code=422, detail="invalid_city")

    if payload.product_slug not in PRODUCT_SLUGS:
        raise HTTPException(status_code=422, detail="invalid_product")

    product_slug = canonical_product_slug(payload.product_slug)
    if payload.tier_qty not in tier_prices_for(payload.product_slug):
        raise HTTPException(status_code=422, detail="invalid_tier")
    product = session.exec(select(Product).where(Product.slug == product_slug)).first()
    if not product or not product.is_active:
        raise HTTPException(status_code=404, detail="product_not_found")

    cross_slug = canonical_product_slug(payload.cross_sell_slug) if payload.cross_sell_slug else None
    if payload.cross_sell_slug:
        if cross_slug == product_slug or payload.cross_sell_slug not in PRODUCT_SLUGS:
            raise HTTPException(status_code=422, detail="invalid_cross_sell")
        if product_slug == "pack-royal-power":
            raise HTTPException(status_code=422, detail="cross_sell_not_available")

    existing = session.exec(select(Order).where(Order.event_id == payload.event_id)).first()
    if existing:
        return _serialize(existing)

    client_ip = _client_ip(request)
    if ip_is_blocked(client_ip):
        raise HTTPException(status_code=403, detail="order_blocked")

    tier_cents, cross_cents, subtotal = compute_subtotal(payload.tier_qty, bool(cross_slug), payload.product_slug)
    order = Order(
        full_name=payload.full_name.strip(),
        phone=e164,
        phone_national=to_national(e164),
        city=customer_city_raw,
        product_slug=product_slug,
        tier_qty=payload.tier_qty,
        tier_price_cents=tier_cents,
        cross_sell_slug=cross_slug,
        cross_sell_price_cents=cross_cents,
        subtotal_cents=subtotal,
        total_cents=subtotal,
        event_id=payload.event_id,
        fbp=payload.fbp,
        fbc=payload.fbc,
        ttclid=payload.ttclid,
        sccid=payload.sccid,
        landing_url=payload.landing_url,
        client_ip=client_ip,
        user_agent=request.headers.get("user-agent"),
    )
    session.add(order)
    session.flush()

    unit = tier_cents // payload.tier_qty
    session.add(
        OrderItem(
            order_id=order.id,
            product_slug=product_slug,
            role="primary",
            quantity=payload.tier_qty,
            unit_price_cents=unit,
            line_total_cents=tier_cents,
        )
    )
    if cross_slug:
        session.add(
            OrderItem(
                order_id=order.id,
                product_slug=cross_slug,
                role="cross_sell",
                quantity=1,
                unit_price_cents=CROSS_SELL_CENTS,
                line_total_cents=CROSS_SELL_CENTS,
            )
        )
    session.commit()
    session.refresh(order)
    _queue_side_effects(background, order, product.name_ar, send_capi=not payload.defer_purchase)
    return _serialize(order)


@router.post("/orders/{order_id}/upsell")
def add_upsell(
    order_id: UUID,
    payload: UpsellCreate,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="order_not_found")
    if order.upsell_slug:
        background.add_task(send_purchase, order, purchase_event_id(order.id))
        return _serialize(order)
    if payload.product_slug not in PRODUCT_SLUGS:
        raise HTTPException(status_code=422, detail="invalid_product")
    upsell_slug = canonical_product_slug(payload.product_slug)
    if upsell_slug in {order.product_slug, order.cross_sell_slug}:
        raise HTTPException(status_code=422, detail="upsell_must_be_different")

    order.upsell_slug = upsell_slug
    order.upsell_price_cents = UPSELL_CENTS
    order.total_cents = order.subtotal_cents + UPSELL_CENTS
    order.status = "upsell_accepted"
    order.updated_at = datetime.now(timezone.utc)
    session.add(
        OrderItem(
            order_id=order.id,
            product_slug=upsell_slug,
            role="upsell",
            quantity=1,
            unit_price_cents=UPSELL_CENTS,
            line_total_cents=UPSELL_CENTS,
        )
    )
    session.add(order)
    session.commit()
    session.refresh(order)
    name = product_name_ar(session, order.product_slug)
    background.add_task(send_purchase, order, purchase_event_id(order.id))
    background.add_task(push_order_to_sheets, order, name)
    return _serialize(order)


@router.post("/orders/{order_id}/purchase")
def finalize_purchase(
    order_id: UUID,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="order_not_found")
    background.add_task(send_purchase, order, purchase_event_id(order.id))
    return _serialize(order)


@router.get("/orders/{order_id}")
def get_order(order_id: UUID, session: Session = Depends(get_session)):
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="order_not_found")
    return _serialize(order)


@router.patch("/orders/{order_id}")
def update_order(
    order_id: str,
    payload: dict | None = Body(default=None),
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    from app.routers.admin import admin_update_order

    return admin_update_order(order_id, payload if isinstance(payload, dict) else {}, admin, session)
