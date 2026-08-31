from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import inspect, or_, text
from sqlmodel import Session, select

from app.db import get_session
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

router = APIRouter(prefix="/api/admin", tags=["admin"])

AdminStatus = Literal["new", "confirmed", "shipped", "delivered", "cancelled"]

NEW_EQUIV = ("pending", "upsell_accepted", "new")
ALLOWED_STATUSES: tuple[str, ...] = ("new", "confirmed", "shipped", "delivered", "cancelled")
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


def _display_status(raw: str) -> str:
    if raw in NEW_EQUIV:
        return "new"
    if raw in ALLOWED_STATUSES:
        return raw
    return "new"


def _pack_label(order: Order) -> str:
    parts = [f"{PACK_NAMES.get(order.product_slug, order.product_slug)} × {order.tier_qty}"]
    if order.cross_sell_slug:
        parts.append(PACK_NAMES.get(order.cross_sell_slug, order.cross_sell_slug))
    if order.upsell_slug:
        parts.append(f"{PACK_NAMES.get(order.upsell_slug, order.upsell_slug)} (عرض)")
    return " + ".join(parts)


def _serialize_order(order: Order) -> dict:
    created = order.created_at
    if created and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return {
        "order_id": str(order.id),
        "created_at": created.isoformat() if created else None,
        "full_name": order.full_name,
        "city": order.city,
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
        "address": order.address,
        "quartier": order.quartier,
        "street": order.street,
        "building": order.building,
        "landmark": order.landmark,
        "delivery_window": order.delivery_window,
        "courier_notes": order.courier_notes,
        "driver_comment": order.courier_notes,
        "region_id": getattr(order, "region_id", None),
        "region": getattr(order, "region_id", None),
        "full_address": order.address,
        "primary_product": order.product_slug,
        "primary_qty": order.tier_qty,
        "bundle_enabled": bool(getattr(order, "bundle_enabled", False) or order.cross_sell_slug),
        "secondary_product": order.cross_sell_slug,
        "secondary_qty": int(getattr(order, "secondary_qty", 1) or 1),
        "total_price": cents_to_mad(order.total_cents),
        "customer_name": order.full_name,
        "source": getattr(order, "source", None),
        "updated_at": order.updated_at.isoformat() if getattr(order, "updated_at", None) else None,
        "confirmed_at": order.confirmed_at.isoformat() if getattr(order, "confirmed_at", None) else None,
        "shipped_at": order.shipped_at.isoformat() if getattr(order, "shipped_at", None) else None,
        "delivered_at": order.delivered_at.isoformat() if getattr(order, "delivered_at", None) else None,
        "cancelled_at": order.cancelled_at.isoformat() if getattr(order, "cancelled_at", None) else None,
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
    if status_value in ("confirmed", "shipped", "delivered") and not order.confirmed_at:
        _assign(order, known, "confirmed_at", now)
    if status_value in ("shipped", "delivered") and not order.shipped_at:
        _assign(order, known, "shipped_at", now)
    if status_value == "delivered" and not order.delivered_at:
        _assign(order, known, "delivered_at", now)
    if status_value == "cancelled" and not order.cancelled_at:
        _assign(order, known, "cancelled_at", now)


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

    if "status" in data and data["status"]:
        if data["status"] not in ALLOWED_STATUSES:
            raise HTTPException(status_code=422, detail="invalid_status")
        _assign(order, known, "status", data["status"])
        _stamp_status(order, data["status"], known)
    if "full_name" in data and data["full_name"]:
        name = str(data["full_name"]).strip()[:160]
        if len(name) < 3:
            raise HTTPException(status_code=422, detail="invalid_name")
        _assign(order, known, "full_name", name)
    if "city" in data and data["city"]:
        _assign(order, known, "city", str(data["city"]).strip()[:120])
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
    token = create_access_token(payload.username.strip())
    body = JSONResponse({"ok": True, "username": payload.username.strip()})
    apply_auth_cookie(body, token)
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
