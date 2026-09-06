from __future__ import annotations

import traceback
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import inspect, or_, text
from sqlmodel import Session, select

from app.db import engine, get_session
from app.dependencies import client_ip, get_current_admin
from app.models import Order
from app.rate_limit import login_limiter
from app.security import (
    admin_configured,
    apply_auth_cookie,
    clear_auth_cookie,
    create_access_token,
    verify_credentials,
)
from app.schemas import OrderUpdate
from app.services.pricing import cents_to_mad
from app.services.page_views import observatory_stats

router = APIRouter(prefix="/api/admin", tags=["admin"])

AdminStatus = Literal["new", "confirmed", "shipped", "delivered", "cancelled"]

NEW_EQUIV = ("pending", "upsell_accepted", "new")
ALLOWED_STATUSES: tuple[str, ...] = ("new", "confirmed", "shipped", "delivered", "cancelled")
STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "new": ("confirmed", "cancelled"),
    "confirmed": ("shipped", "cancelled"),
    "shipped": ("delivered", "cancelled"),
    "delivered": (),
    "cancelled": ("new", "confirmed"),
}
REGION_IDS = tuple(f"MA{i:02d}" for i in range(1, 13))

PACK_NAMES = {
    "quran": "USB القرآن الكريم",
    "kids": "USB تعليم الأطفال",
    "music": "USB الأغاني والموسيقى",
    "educative": "الفلاشة التعليمية الذكية",
    "extra": "مفتاح إضافي بسعر العرض",
}


class AdminLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)
    remember: bool = False
    rememberMe: bool = False


def _display_status(raw: str) -> str:
    if raw in NEW_EQUIV:
        return "new"
    if raw in ALLOWED_STATUSES:
        return raw
    return "new"


def _assert_status_transition(current_raw: str, next_status: str) -> None:
    current = _display_status(current_raw or "new")
    nxt = _display_status(next_status or "")
    if current == nxt:
        return
    if nxt not in STATUS_TRANSITIONS.get(current, ()):
        raise HTTPException(status_code=422, detail="invalid_status_transition")


def _composed_address(order: Order) -> str:
    stored = str(getattr(order, "address", None) or getattr(order, "full_address", None) or "").strip()
    if stored:
        return stored
    bits = [
        str(getattr(order, field, None) or "").strip()
        for field in ("quartier", "street", "building", "landmark")
    ]
    return "، ".join(part for part in bits if part)


def _has_complete_confirm_details(order: Order) -> bool:
    name = str(getattr(order, "full_name", "") or "").strip()
    city = str(getattr(order, "city", "") or "").strip()
    phone = str(getattr(order, "phone", "") or getattr(order, "phone_national", "") or "").strip()
    address = _composed_address(order)
    if len(name) < 3 or len(city) < 2 or not phone or len(address) < 8:
        return False
    rest = address.replace(city, " ")
    for ch in "،,.- \t":
        rest = rest.replace(ch, "")
    return len(rest) >= 5


def _pack_label(order: Order) -> str:
    parts = [f"{PACK_NAMES.get(order.product_slug, order.product_slug)} × {order.tier_qty}"]
    if order.cross_sell_slug:
        parts.append(PACK_NAMES.get(order.cross_sell_slug, order.cross_sell_slug))
    if order.upsell_slug:
        parts.append(f"{PACK_NAMES.get(order.upsell_slug, order.upsell_slug)} (عرض)")
    return " + ".join(parts)


def _iso(value: object) -> str | None:
    if value is None:
        return None
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        try:
            dt = value
            tzinfo = getattr(dt, "tzinfo", None)
            if tzinfo is None and hasattr(dt, "replace"):
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _serialize_order(order: Order) -> dict:
    return {
        "order_id": str(order.id),
        "created_at": _iso(order.created_at),
        "full_name": order.full_name,
        "city": order.city,
        "shipping_city": getattr(order, "shipping_city", None),
        "phone": order.phone,
        "phone_national": order.phone_national,
        "product_slug": order.product_slug,
        "tier_qty": order.tier_qty,
        "cross_sell_slug": order.cross_sell_slug,
        "upsell_slug": order.upsell_slug,
        "pack_label": _pack_label(order),
        "total": cents_to_mad(order.total_cents),
        "currency": order.currency,
        "status": _display_status(order.status),
        "raw_status": order.status,
        "address": getattr(order, "address", None),
        "quartier": getattr(order, "quartier", None),
        "street": getattr(order, "street", None),
        "building": getattr(order, "building", None),
        "landmark": getattr(order, "landmark", None),
        "delivery_window": getattr(order, "delivery_window", None),
        "courier_notes": getattr(order, "courier_notes", None),
        "driver_comment": getattr(order, "courier_notes", None),
        "region_id": getattr(order, "region_id", None),
        "region": getattr(order, "region_id", None),
        "full_address": getattr(order, "address", None),
        "primary_product": order.product_slug,
        "primary_qty": order.tier_qty,
        "bundle_enabled": bool(getattr(order, "bundle_enabled", False) or order.cross_sell_slug),
        "secondary_product": order.cross_sell_slug,
        "secondary_qty": int(getattr(order, "secondary_qty", 1) or 1),
        "total_price": cents_to_mad(order.total_cents),
        "customer_name": order.full_name,
        "source": getattr(order, "source", None),
        "updated_at": _iso(getattr(order, "updated_at", None)),
        "confirmed_at": _iso(getattr(order, "confirmed_at", None)),
        "shipped_at": _iso(getattr(order, "shipped_at", None)),
        "delivered_at": _iso(getattr(order, "delivered_at", None)),
        "cancelled_at": _iso(getattr(order, "cancelled_at", None)),
        "meta_livraison_code": getattr(order, "meta_livraison_code", None),
        "meta_livraison_sent_at": _iso(getattr(order, "meta_livraison_sent_at", None)),
        "meta_livraison_ticket_url": getattr(order, "meta_livraison_ticket_url", None),
    }


def _resolve_region(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    upper = raw.upper()
    if upper in REGION_IDS:
        return upper
    if len(raw) <= 8:
        return upper
    return None


def _stamp_status(order: Order, status_value: str, cols: set[str] | None = None) -> None:
    now = datetime.now(timezone.utc)
    known = cols if cols is not None else set()
    if status_value == "new":
        _assign(order, known, "confirmed_at", None)
        _assign(order, known, "shipped_at", None)
        _assign(order, known, "delivered_at", None)
        _assign(order, known, "cancelled_at", None)
        return
    if status_value in ("confirmed", "shipped", "delivered") and not order.confirmed_at:
        _assign(order, known, "confirmed_at", now)
    if status_value in ("shipped", "delivered") and not order.shipped_at:
        _assign(order, known, "shipped_at", now)
    if status_value == "delivered" and not order.delivered_at:
        _assign(order, known, "delivered_at", now)
    if status_value == "cancelled":
        if not order.cancelled_at:
            _assign(order, known, "cancelled_at", now)
        return
    _assign(order, known, "cancelled_at", None)
    if status_value == "confirmed":
        _assign(order, known, "shipped_at", None)
        _assign(order, known, "delivered_at", None)
    elif status_value == "shipped":
        _assign(order, known, "delivered_at", None)


def _order_column_names(session: Session) -> set[str]:
    try:
        return {col["name"] for col in inspect(session.get_bind()).get_columns("orders")}
    except Exception:
        return set()


def _assign(order: Order, cols: set[str], name: str, value: object) -> None:
    if cols and name not in cols:
        return
    setattr(order, name, value)


def _load_order(session: Session, order_id: str) -> Order | None:
    raw = (order_id or "").strip()
    if not raw:
        return None
    try:
        return session.get(Order, UUID(raw))
    except Exception:
        try:
            return session.get(Order, raw)
        except Exception:
            return None


def apply_order_update(order: Order, payload: OrderUpdate | dict[str, Any], cols: set[str] | None = None) -> Order:
    known = cols if cols is not None else set()
    if isinstance(payload, OrderUpdate):
        data = payload.model_dump(exclude_unset=True)
    else:
        try:
            data = OrderUpdate.model_validate(payload or {}).model_dump(exclude_unset=True)
        except Exception:
            data = dict(payload or {})
    if "customer_name" in data and "full_name" not in data:
        data["full_name"] = data["customer_name"]
    if "full_address" in data and "address" not in data:
        data["address"] = data["full_address"]
    if "region" in data and "region_id" not in data:
        data["region_id"] = data["region"]
    if "primary_product" in data and "product_slug" not in data:
        data["product_slug"] = data["primary_product"]
    if "primary_qty" in data and "tier_qty" not in data:
        data["tier_qty"] = data["primary_qty"]
    if "total_price" in data and "total_mad" not in data:
        data["total_mad"] = data["total_price"]
    if "driver_comment" in data and "courier_notes" not in data:
        data["courier_notes"] = data["driver_comment"]
    if "secondary_product" in data and "cross_sell_slug" not in data:
        data["cross_sell_slug"] = data["secondary_product"]
    if data.get("bundle_enabled") is False:
        data["cross_sell_slug"] = None

    current_status = _display_status(str(order.status or "new"))
    if "status" in data and data["status"]:
        if data["status"] not in ALLOWED_STATUSES:
            raise HTTPException(status_code=422, detail="invalid_status")
        _assert_status_transition(current_status, str(data["status"]))
        _assign(order, known, "status", data["status"])
        _stamp_status(order, data["status"], known)
    if "full_name" in data and data["full_name"]:
        name = str(data["full_name"]).strip()[:160]
        if len(name) < 3:
            raise HTTPException(status_code=422, detail="invalid_name")
        _assign(order, known, "full_name", name)
    if "city" in data and data["city"]:
        _assign(order, known, "city", str(data["city"]).strip()[:120])
    if "shipping_city" in data:
        shipping = str(data["shipping_city"] or "").strip()[:160] or None
        _assign(order, known, "shipping_city", shipping)
    if "product_slug" in data and data["product_slug"]:
        _assign(order, known, "product_slug", str(data["product_slug"]))
    if "tier_qty" in data and data["tier_qty"]:
        qty = int(data["tier_qty"])
        if qty < 1 or qty > 20:
            raise HTTPException(status_code=422, detail="invalid_qty")
        _assign(order, known, "tier_qty", qty)
    if "total_mad" in data and data["total_mad"] is not None:
        cents = int(round(float(data["total_mad"]) * 100))
        if cents < 100:
            raise HTTPException(status_code=422, detail="invalid_price")
        _assign(order, known, "total_cents", cents)
        _assign(order, known, "subtotal_cents", cents)
        _assign(order, known, "tier_price_cents", cents)
    for field in ("quartier", "street", "building", "landmark", "delivery_window", "courier_notes"):
        if field in data:
            value = str(data[field] or "").strip() or None
            _assign(order, known, field, value)
    if "address" in data:
        _assign(order, known, "address", (str(data["address"]) if data["address"] is not None else "").strip() or None)
    if "region_id" in data:
        _assign(order, known, "region_id", _resolve_region(str(data["region_id"]) if data["region_id"] is not None else None))
    if "bundle_enabled" in data:
        _assign(order, known, "bundle_enabled", bool(data["bundle_enabled"]))
    if "secondary_qty" in data and data["secondary_qty"]:
        qty = int(data["secondary_qty"])
        if qty < 1 or qty > 20:
            raise HTTPException(status_code=422, detail="invalid_qty")
        _assign(order, known, "secondary_qty", qty)
    if "cross_sell_slug" in data:
        slug = data["cross_sell_slug"] or None
        _assign(order, known, "cross_sell_slug", slug)
        if not slug:
            _assign(order, known, "bundle_enabled", False)
        else:
            _assign(order, known, "bundle_enabled", True)
    if "cross_sell_price_mad" in data and data["cross_sell_price_mad"] is not None:
        _assign(order, known, "cross_sell_price_cents", int(round(float(data["cross_sell_price_mad"]) * 100)))
    _assign(order, known, "updated_at", datetime.now(timezone.utc))
    next_status = _display_status(str(getattr(order, "status", current_status) or current_status))
    if next_status == "confirmed" and current_status != "confirmed" and not _has_complete_confirm_details(order):
        raise HTTPException(status_code=422, detail="confirmation_details_required")
    return order


def _status_filter(value: str):
    if value == "new":
        return Order.status.in_(NEW_EQUIV)
    return Order.status == value


@router.post("/login")
def admin_login(payload: AdminLoginIn, request: Request):
    ip = client_ip(request)
    retry_after = login_limiter.retry_after(ip)
    if retry_after > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too_many_attempts",
            headers={"Retry-After": str(retry_after)},
        )

    if not admin_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="admin_not_configured")

    if not verify_credentials(payload.username.strip(), payload.password):
        locked_for = login_limiter.record_failure(ip)
        headers = {"Retry-After": str(locked_for)} if locked_for else None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_credentials",
            headers=headers,
        )

    login_limiter.record_success(ip)
    remember = bool(payload.remember or payload.rememberMe)
    token = create_access_token(payload.username.strip(), remember=remember)
    body = JSONResponse({"ok": True, "username": payload.username.strip()})
    apply_auth_cookie(body, token, remember=remember)
    return body


@router.post("/logout")
def admin_logout():
    response = JSONResponse({"ok": True})
    clear_auth_cookie(response)
    return response


@router.get("/me")
def admin_me(admin: dict = Depends(get_current_admin)):
    return {"ok": True, "username": admin["sub"], "role": admin.get("role")}


@router.get("/stats")
def admin_stats(
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    rows = session.exec(select(Order.status, Order.total_cents)).all()
    new_orders = confirmed = shipped = delivered = cancelled = revenue_cents = 0
    for raw_status, cents in rows:
        display = _display_status(raw_status or "pending")
        if display == "new":
            new_orders += 1
        elif display == "confirmed":
            confirmed += 1
        elif display == "shipped":
            shipped += 1
        elif display == "delivered":
            delivered += 1
        elif display == "cancelled":
            cancelled += 1
        if display != "cancelled":
            revenue_cents += int(cents or 0)

    won = confirmed + shipped + delivered
    processed = won + cancelled
    rate = round((won / processed) * 100, 1) if processed else 0.0

    return {
        "revenue": cents_to_mad(revenue_cents),
        "currency": "MAD",
        "new_orders": new_orders,
        "confirmed_orders": confirmed,
        "shipped_orders": shipped,
        "delivered_orders": delivered,
        "cancelled_orders": cancelled,
        "confirmation_rate": rate,
        "total_orders": len(rows),
    }


@router.get("/views")
def admin_views(
    range_name: str = Query("today", alias="range"),
    date: str | None = Query(None),
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    allowed = {"today", "week", "month", "custom"}
    resolved = range_name if range_name in allowed else "today"
    return observatory_stats(session, resolved, date)


@router.get("/orders")
def admin_orders(
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
    q: str = Query(default="", max_length=80),
    city: str = Query(default="", max_length=80),
    status_filter: str = Query(default="", alias="status", max_length=32),
    limit: int = Query(default=400, ge=1, le=2000),
):
    _ = admin
    stmt = select(Order)
    needle = q.strip()
    if needle:
        like = f"%{needle}%"
        stmt = stmt.where(
            or_(
                Order.full_name.ilike(like),
                Order.phone.ilike(like),
                Order.phone_national.ilike(like),
                Order.city.ilike(like),
            )
        )
    city_val = city.strip()
    if city_val:
        stmt = stmt.where(Order.city == city_val)
    status_val = status_filter.strip()
    if status_val:
        if status_val not in ALLOWED_STATUSES:
            raise HTTPException(status_code=422, detail="invalid_status")
        stmt = stmt.where(_status_filter(status_val))

    stmt = stmt.order_by(Order.created_at.desc()).limit(limit)
    orders = session.exec(stmt).all()
    cities = session.exec(select(Order.city).distinct().order_by(Order.city)).all()
    return {
        "orders": [_serialize_order(o) for o in orders],
        "cities": [c for c in cities if c],
    }


@router.post("/orders", status_code=201)
def admin_create_order(
    payload: dict[str, Any] | None = Body(default=None),
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    body = payload if isinstance(payload, dict) else {}
    name = str(body.get("full_name") or "").strip()[:120]
    if len(name) < 3:
        raise HTTPException(status_code=422, detail="invalid_name")
    try:
        from app.services.phone import digits_only, normalize_ma_phone, to_national

        raw_phone = str(body.get("phone") or "")
        if len(digits_only(raw_phone)) != 10:
            raise ValueError("invalid_ma_phone")
        e164 = normalize_ma_phone(raw_phone)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="invalid_ma_phone") from exc
    if not e164:
        raise HTTPException(status_code=422, detail="invalid_ma_phone")
    city = str(body.get("city") or "").strip()[:80]
    if len(city) < 2:
        raise HTTPException(status_code=422, detail="invalid_city")
    try:
        from app.services.cities import find_city

        hit = find_city(city)
        if hit and hit.get("ar"):
            city = str(hit["ar"])[:80]
    except Exception:
        pass
    status_value = str(body.get("status") or "confirmed")
    if status_value not in ALLOWED_STATUSES:
        raise HTTPException(status_code=422, detail="invalid_status")
    qty = max(1, min(20, int(body.get("tier_qty") or 1)))
    try:
        cents = int(round(float(body.get("total_mad") or 0) * 100))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="invalid_price") from exc
    if cents < 100:
        raise HTTPException(status_code=422, detail="invalid_price")
    slug = str(body.get("product_slug") or "quran")
    if slug not in ("quran", "kids", "music", "educative"):
        slug = "quran"
    allowed_cross = ("quran", "kids", "music", "educative", "extra")
    cross = str(body.get("cross_sell_slug") or body.get("secondary_product") or "").strip() or None
    if cross not in allowed_cross:
        cross = None
    bundle = bool(body.get("bundle_enabled")) and bool(cross)
    secondary_qty = max(1, min(20, int(body.get("secondary_qty") or 1)))
    address = str(body.get("address") or body.get("full_address") or "").strip() or None
    notes = str(body.get("courier_notes") or body.get("driver_comment") or "").strip() or None
    order_id = uuid4()
    now = datetime.now(timezone.utc)
    order = Order(
        id=order_id,
        full_name=name,
        phone=e164,
        phone_national=to_national(e164),
        city=city,
        product_slug=slug,
        tier_qty=qty,
        tier_price_cents=cents,
        subtotal_cents=cents,
        total_cents=cents,
        status=status_value,
        event_id=f"admin-{order_id}",
        source="admin",
        updated_at=now,
        address=address,
        quartier=str(body.get("quartier") or "").strip() or None,
        street=str(body.get("street") or "").strip() or None,
        building=str(body.get("building") or "").strip() or None,
        landmark=str(body.get("landmark") or "").strip() or None,
        courier_notes=notes,
        region_id=_resolve_region(str(body.get("region_id") or body.get("region") or "") or None),
        cross_sell_slug=cross if bundle else None,
        bundle_enabled=bundle,
        secondary_qty=secondary_qty if bundle else 1,
    )
    _stamp_status(order, status_value, _order_column_names(session))
    try:
        session.add(order)
        session.commit()
        session.refresh(order)
        return _serialize_order(order)
    except Exception:
        session.rollback()
        session.execute(
            text(
                """
                INSERT INTO orders (id, full_name, phone, city, product_slug, tier_qty, total_cents, status, event_id)
                VALUES (:id, :full_name, :phone, :city, :product_slug, :tier_qty, :total_cents, :status, :event_id)
                """
            ),
            {
                "id": str(order_id),
                "full_name": name,
                "phone": e164,
                "city": city,
                "product_slug": slug,
                "tier_qty": qty,
                "total_cents": cents,
                "status": status_value,
                "event_id": f"admin-{order_id}",
            },
        )
        session.commit()
        created = _load_order(session, str(order_id))
        if not created:
            raise HTTPException(status_code=500, detail="create_failed")
        return _serialize_order(created)


@router.patch("/orders/{order_id}")
def admin_update_order(
    order_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    body = payload if isinstance(payload, dict) else {}
    order = _load_order(session, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="order_not_found")
    cols = _order_column_names(session)
    defined = {key: value for key, value in body.items() if value is not None}
    status_only = set(defined) <= {"status"} and "status" in defined
    if status_only:
        status_value = str(defined["status"])
        if status_value not in ALLOWED_STATUSES:
            raise HTTPException(status_code=422, detail="invalid_status")
        _assert_status_transition(str(order.status or "new"), status_value)
        if _display_status(status_value) == "confirmed" and _display_status(str(order.status or "")) != "confirmed":
            if not _has_complete_confirm_details(order):
                raise HTTPException(status_code=422, detail="confirmation_details_required")
        try:
            _assign(order, cols, "status", status_value)
            _stamp_status(order, status_value, cols)
            _assign(order, cols, "updated_at", datetime.now(timezone.utc))
            session.add(order)
            session.commit()
            session.refresh(order)
            return _serialize_order(order)
        except HTTPException:
            session.rollback()
            raise
        except Exception:
            session.rollback()
            session.execute(
                text("UPDATE orders SET status = :status WHERE id = :id"),
                {"status": status_value, "id": str(order.id)},
            )
            session.commit()
            order = _load_order(session, str(order.id))
            if not order:
                raise HTTPException(status_code=404, detail="order_not_found")
            return _serialize_order(order)
    try:
        apply_order_update(order, body, cols)
        session.add(order)
        session.commit()
        session.refresh(order)
        return _serialize_order(order)
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        data = body
        name = str(data.get("full_name") or data.get("customer_name") or data.get("fullName") or order.full_name or "").strip()[:160]
        city = str(data.get("city") or order.city or "").strip()[:120]
        slug = str(data.get("product_slug") or data.get("primary_product") or data.get("productSlug") or order.product_slug)
        qty = int(data.get("tier_qty") or data.get("primary_qty") or data.get("tierQty") or order.tier_qty or 1)
        total = data.get("total_mad") if data.get("total_mad") is not None else data.get("total_price") or data.get("totalMad") or data.get("totalPrice")
        cents = int(round(float(total) * 100)) if total is not None else order.total_cents
        status_value = str(data.get("status") or order.status)
        if data.get("status"):
            _assert_status_transition(str(order.status or "new"), status_value)
        try:
            session.execute(
                text(
                    """
                    UPDATE orders SET
                      full_name = :full_name,
                      city = :city,
                      product_slug = :product_slug,
                      tier_qty = :tier_qty,
                      total_cents = :total_cents,
                      status = :status,
                      updated_at = now()
                    WHERE id = :id
                    """
                ),
                {
                    "id": str(order.id),
                    "full_name": name or order.full_name,
                    "city": city or order.city,
                    "product_slug": slug,
                    "tier_qty": qty,
                    "total_cents": cents,
                    "status": status_value,
                },
            )
            session.commit()
        except Exception as exc:
            session.rollback()
            raise HTTPException(status_code=500, detail="update_failed") from exc
        order = _load_order(session, str(order.id))
        if not order:
            raise HTTPException(status_code=404, detail="order_not_found")
        return _serialize_order(order)


@router.post("/orders/{order_id}/livraison")
async def admin_send_livraison(order_id: str, request: Request):
    try:
        with Session(engine) as session:
            auth = (request.headers.get("authorization") or "").strip()
            creds = None
            if auth.lower().startswith("bearer ") and len(auth) > 7:
                creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth.split(" ", 1)[1].strip())
            try:
                get_current_admin(request, creds)
            except HTTPException as exc:
                print("401 details:" if exc.status_code == 401 else "admin auth error:", exc.detail, flush=True)
                return JSONResponse(
                    {
                        "success": False,
                        "message": "جلسة الأدمن غير صالحة. أعد تسجيل الدخول." if exc.status_code == 401 else str(exc.detail),
                        "origin": "admin_session",
                        "error": str(exc.detail),
                    },
                    status_code=exc.status_code,
                )

            import os

            from app.services.meta_livraison import configured, create_colis, debug_credentials

            api_key = (os.getenv("META_LIVRAISON_API_KEY") or os.environ.get("META_LIVRAISON_API_KEY") or "").strip()
            api_secret = (os.getenv("META_LIVRAISON_API_SECRET") or os.environ.get("META_LIVRAISON_API_SECRET") or "").strip()
            base_url = (
                os.getenv("META_LIVRAISON_BASE_URL")
                or os.environ.get("META_LIVRAISON_BASE_URL")
                or "https://api.metalivraison.ma/colis-service"
            ).rstrip("/")
            print(f"[DEBUG META LIVRAISON] Base URL: {base_url}", flush=True)
            print(f"[DEBUG META LIVRAISON] Key length: {len(api_key)}, Key prefix: {api_key[:6]}...", flush=True)
            print(f"[DEBUG META LIVRAISON] Secret length: {len(api_secret)}, Secret prefix: {api_secret[:6]}...", flush=True)
            debug_credentials(api_key, api_secret, base_url)

            if not configured(api_key, api_secret):
                return JSONResponse(
                    {"success": False, "detail": "META_LIVRAISON_API_KEY or META_LIVRAISON_API_SECRET is missing"},
                    status_code=400,
                )
            order = _load_order(session, order_id)
            if not order:
                return JSONResponse({"success": False, "detail": "order_not_found"}, status_code=404)
            if _display_status(str(getattr(order, "status", "") or "")) == "cancelled":
                return JSONResponse({"success": False, "detail": "cannot_ship_cancelled"}, status_code=400)
            existing = str(getattr(order, "meta_livraison_code", "") or "").strip()
            if existing:
                return JSONResponse({**_serialize_order(order), "success": True})
            if not _has_complete_confirm_details(order):
                return JSONResponse({"success": False, "detail": "confirmation_details_required"}, status_code=400)

            result = create_colis(order, api_key=api_key, api_secret=api_secret, base_url=base_url)
            if not result.get("ok"):
                return JSONResponse(
                    status_code=400,
                    content=jsonable_encoder(
                        {
                            "success": False,
                            "origin": "meta_livraison",
                            "status_code": int(result.get("status") or 400),
                            "detail": result.get("detail") if result.get("detail") not in (None, "") else result.get("text"),
                        }
                    ),
                )

            cols = _order_column_names(session)
            code = str(result.get("code") or "").strip() or str(order.id).replace("-", "")[:8].upper()
            ticket_url = str(result.get("ticket_url") or "").strip() or None
            now = datetime.now(timezone.utc)
            _assign(order, cols, "meta_livraison_code", code)
            _assign(order, cols, "meta_livraison_ticket_url", ticket_url)
            _assign(order, cols, "meta_livraison_sent_at", getattr(order, "meta_livraison_sent_at", None) or now)
            _assign(order, cols, "status", "shipped")
            _stamp_status(order, "shipped", cols)
            _assign(order, cols, "updated_at", now)
            session.add(order)
            session.commit()
            session.refresh(order)
            return JSONResponse({**_serialize_order(order), "success": True})
    except BaseException as e:
        tb = traceback.format_exc()
        print(f"[LIVRAISON_FATAL_ERROR] {tb}", flush=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error_type": type(e).__name__,
                "detail": str(e),
                "traceback": tb,
            },
        )
