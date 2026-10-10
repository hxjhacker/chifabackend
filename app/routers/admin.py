from __future__ import annotations

import json
import os
import traceback
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, inspect, or_, text
from sqlmodel import Session, col, select

from app.db import engine, get_session
from app.dependencies import client_ip, get_current_admin
from app.models import Order, Product
from app.services.catalog import clean_product_code, find_product, resolve_order_slug
from app.services.quick_livraison import create_quick_stock_order, unmapped_city_detail
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
from app.services.logistics_analytics import logistics_analytics
from app.services.city_tarifs import list_lookup_tarifs, load_tarif_index, serialize_tarifs, sync_meta_city_tarifs
from app.services.carrier_rates import (
    apply_city_rate_patch,
    extract_quick_billed_fee,
    resolve_dispatch_shipping_cost,
)
from app.services.carriers import (
    carrier_catalog,
    get_carrier,
    normalize_carrier,
    run_sync,
)
from app.services.carriers.quick import is_dummy_parcel_code, quick_client_code, sync_quick_districts
from app.services.meta_livraison_cities import is_official_meta_city, resolve_meta_city
from app.utils.regions import region_id_for_city

router = APIRouter(prefix="/api/admin", tags=["admin"])

AdminStatus = Literal["new", "confirmed", "shipped", "delivered", "returned", "cancelled", "out_of_zone"]

NEW_EQUIV = ("pending", "upsell_accepted", "new")
ALLOWED_STATUSES: tuple[str, ...] = ("new", "confirmed", "shipped", "delivered", "returned", "cancelled", "out_of_zone")
STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "new": ("confirmed", "cancelled"),
    "confirmed": ("shipped", "out_of_zone", "cancelled"),
    "shipped": ("delivered", "returned", "out_of_zone", "cancelled"),
    "delivered": (),
    "returned": (),
    "cancelled": ("new", "confirmed"),
    "out_of_zone": ("shipped", "returned", "cancelled"),
}
REGION_IDS = tuple(f"MA{i:02d}" for i in range(1, 13))

PACK_NAMES = {
    "quran": "USB القرآن",
    "taalim": "USB التعليمي",
    "music": "USB الموسيقى",
    "zit_alfasokh": "زيت الفسوخ",
    "alkhatm_alrijali": "الخاتم الرجالي",
    "almisk_alabyad": "المسك الأبيض",
    "kids": "USB تعليم الأطفال",
    "educative": "الفلاشة التعليمية الذكية",
    "extra": "مفتاح إضافي بسعر العرض",
    "pack-royal-power": "الباك الملكي",
}


class AdminLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)
    remember: bool = False
    rememberMe: bool = False


class BulkOrderIds(BaseModel):
    order_ids: list[str] = Field(default_factory=list)
    tracking_numbers: list[str] = Field(default_factory=list)
    carrier: str | None = None


class QuickStockDispatchRequest(BaseModel):
    product_id: int | None = Field(default=None, ge=1)
    quantity: int = Field(default=1, ge=1)


_QUICK_ORDER_SNAPSHOT_ATTRS = (
    "id",
    "full_name",
    "customer_name",
    "city",
    "shipping_city",
    "region_id",
    "phone",
    "phone_national",
    "address",
    "quartier",
    "street",
    "building",
    "landmark",
    "courier_notes",
    "total_cents",
    "total_price",
    "price",
    "total_mad",
    "tier_qty",
    "product_slug",
    "status",
    "meta_livraison_code",
)


def _snapshot_order(order: Order) -> SimpleNamespace:
    return SimpleNamespace(**{name: getattr(order, name, None) for name in _QUICK_ORDER_SNAPSHOT_ATTRS})


def _display_status(raw: str) -> str:
    if raw in NEW_EQUIV:
        return "new"
    if raw == "in_shipping":
        return "shipped"
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
    return "ØŒ ".join(part for part in bits if part)


def _has_complete_confirm_details(order: Order) -> bool:
    name = str(getattr(order, "full_name", "") or "").strip()
    city = str(getattr(order, "city", "") or "").strip()
    phone = str(getattr(order, "phone", "") or getattr(order, "phone_national", "") or "").strip()
    address = _composed_address(order)
    if len(name) < 3 or len(city) < 2 or not phone or len(address) < 8:
        return False
    rest = address.replace(city, " ")
    for ch in "ØŒ,.- \t":
        rest = rest.replace(ch, "")
    return len(rest) >= 5


def _product_code_map(session: Session | None) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if session is None:
        return mapping
    cached = getattr(session, "_product_code_cache", None)
    if isinstance(cached, dict):
        return cached
    try:
        for product in session.exec(select(Product)).all():
            code = str(getattr(product, "code", None) or product.slug or "").strip()
            if code and "/" not in code:
                code = code.upper()
            if not code:
                continue
            mapping[product.slug] = code
            mapping[code] = code
            mapping[code.upper()] = code
            mapping[str(product.id)] = code
        setattr(session, "_product_code_cache", mapping)
    except Exception:
        mapping = {}
    return mapping


def _order_product_code(order: Order, session: Session | None = None) -> str:
    slug = str(getattr(order, "product_slug", "") or "").strip()
    mapped = _product_code_map(session).get(slug)
    if mapped:
        return mapped
    return clean_product_code(slug) or slug.upper()


def _quick_product_id_map(session: Session | None) -> dict[str, int]:
    mapping: dict[str, int] = {}
    if session is None:
        return mapping
    cached = getattr(session, "_quick_product_id_cache", None)
    if isinstance(cached, dict):
        return cached
    try:
        for product in session.exec(select(Product)).all():
            raw = getattr(product, "quick_product_id", None)
            try:
                value = int(raw) if raw not in (None, "") else 0
            except (TypeError, ValueError):
                continue
            if value < 1:
                continue
            mapping[product.slug] = value
            code = str(getattr(product, "code", None) or "").strip().upper()
            if code:
                mapping[code] = value
            mapping[str(product.id)] = value
        setattr(session, "_quick_product_id_cache", mapping)
    except Exception:
        mapping = {}
    return mapping


def _order_quick_product_id(order: Order, session: Session | None = None) -> int | None:
    slug = str(getattr(order, "product_slug", "") or "").strip()
    mapped = _quick_product_id_map(session)
    return mapped.get(slug) or mapped.get(slug.upper()) or mapped.get(clean_product_code(slug))


def _quick_stock_map(session: Session | None) -> dict[str, bool]:
    mapping: dict[str, bool] = {}
    if session is None:
        return mapping
    cached = getattr(session, "_quick_stock_cache", None)
    if isinstance(cached, dict):
        return cached
    try:
        for product in session.exec(select(Product)).all():
            flag = bool(getattr(product, "is_quick_stock", False))
            mapping[product.slug] = flag
            code = str(getattr(product, "code", None) or "").strip()
            if code:
                mapping[code] = flag
                mapping[code.upper()] = flag
            mapping[str(product.id)] = flag
        setattr(session, "_quick_stock_cache", mapping)
    except Exception:
        mapping = {}
    return mapping


def _order_is_quick_stock(order: Order, session: Session | None = None) -> bool:
    slug = str(getattr(order, "product_slug", "") or "").strip()
    mapped = _quick_stock_map(session)
    if slug in mapped:
        return bool(mapped[slug])
    return bool(mapped.get(slug.upper()) or mapped.get(clean_product_code(slug)))


def _product_labels(session: Session | None) -> dict[str, str]:
    labels = dict(PACK_NAMES)
    if session is None:
        return labels
    cached = getattr(session, "_product_labels_cache", None)
    if isinstance(cached, dict):
        return cached
    try:
        for product in session.exec(select(Product)).all():
            labels[product.slug] = product.name_ar
            code = getattr(product, "code", None)
            if code:
                labels[str(code)] = product.name_ar
        setattr(session, "_product_labels_cache", labels)
    except Exception:
        pass
    return labels


def _pack_name(slug: str | None, session: Session | None = None) -> str:
    token = str(slug or "").strip()
    if not token:
        return ""
    return _product_labels(session).get(token, token)


def _pack_label(order: Order, session: Session | None = None) -> str:
    slug = str(order.product_slug or "").strip()
    qty = int(order.tier_qty or 1)
    primary = _pack_name(slug, session) if slug == "pack-royal-power" else f"{_pack_name(slug, session)} × {qty}"
    parts = [primary]
    if order.cross_sell_slug:
        parts.append(_pack_name(order.cross_sell_slug, session))
    if order.upsell_slug:
        parts.append(f"{_pack_name(order.upsell_slug, session)} (عرض)")
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


def _order_tracking_code(order: Order) -> str | None:
    code = str(getattr(order, "meta_livraison_code", None) or "").strip() or None
    if not code:
        return None
    if normalize_carrier(getattr(order, "carrier", None)) == "quick_livraison" and is_dummy_parcel_code(code):
        return quick_client_code(order) or code
    return code


def _serialize_order(order: Order, session: Session | None = None) -> dict:
    tracking = _order_tracking_code(order)
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
        "pack_label": _pack_label(order, session),
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
        "assigned_team_member_id": getattr(order, "assigned_team_member_id", "mohammed"),
        "updated_at": _iso(getattr(order, "updated_at", None)),
        "confirmed_at": _iso(getattr(order, "confirmed_at", None)),
        "shipped_at": _iso(getattr(order, "shipped_at", None)),
        "delivered_at": _iso(getattr(order, "delivered_at", None)),
        "cancelled_at": _iso(getattr(order, "cancelled_at", None)),
        "meta_livraison_code": tracking,
        "meta_livraison_sent_at": _iso(getattr(order, "meta_livraison_sent_at", None)),
        "meta_livraison_ticket_url": getattr(order, "meta_livraison_ticket_url", None),
        "carrier": normalize_carrier(getattr(order, "carrier", None)),
        "carrier_status": getattr(order, "carrier_status", None),
        "dispatched_at": _iso(getattr(order, "dispatched_at", None)),
        "shipping_cost": getattr(order, "shipping_cost", None),
        "product_code": _order_product_code(order, session),
        "quick_product_id": _order_quick_product_id(order, session),
        "is_quick_stock": _order_is_quick_stock(order, session),
        "tracking_number": tracking,
        "code_envoi": tracking,
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
    if status_value in ("confirmed", "shipped", "delivered", "returned", "out_of_zone") and not order.confirmed_at:
        _assign(order, known, "confirmed_at", now)
    if status_value in ("shipped", "delivered", "returned", "out_of_zone") and not order.shipped_at:
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
    elif status_value in ("shipped", "returned", "out_of_zone"):
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


MAX_BULK = 80


def _bulk_tokens(payload: BulkOrderIds) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in list(payload.order_ids or []) + list(payload.tracking_numbers or []):
        token = str(raw or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= MAX_BULK:
            break
    return out


def _load_order_or_tracking(session: Session, token: str) -> Order | None:
    order = _load_order(session, token)
    if order:
        return order
    code = (token or "").strip()
    if not code:
        return None
    return session.exec(select(Order).where(Order.meta_livraison_code == code)).first()


def _meta_creds() -> tuple[str, str, str]:
    api_key = (os.getenv("META_LIVRAISON_API_KEY") or os.environ.get("META_LIVRAISON_API_KEY") or "").strip()
    api_secret = (os.getenv("META_LIVRAISON_API_SECRET") or os.environ.get("META_LIVRAISON_API_SECRET") or "").strip()
    base_url = (
        os.getenv("META_LIVRAISON_BASE_URL")
        or os.environ.get("META_LIVRAISON_BASE_URL")
        or "https://api.metalivraison.ma/colis-service"
    ).rstrip("/")
    return api_key, api_secret, base_url


def _detail_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _persist_shipped(
    session: Session,
    order: Order,
    code: str,
    ticket_url: str | None,
    *,
    commit: bool = True,
    carrier: str | None = None,
    shipping_cost: float | None = None,
) -> None:
    cols = _order_column_names(session)
    now = datetime.now(timezone.utc)
    carrier_id = normalize_carrier(carrier or getattr(order, "carrier", None))
    _assign(order, cols, "meta_livraison_code", code)
    _assign(order, cols, "meta_livraison_ticket_url", ticket_url)
    _assign(order, cols, "meta_livraison_sent_at", getattr(order, "meta_livraison_sent_at", None) or now)
    _assign(order, cols, "carrier", carrier_id)
    _assign(order, cols, "carrier_status", "sent_to_carrier")
    _assign(order, cols, "dispatched_at", getattr(order, "dispatched_at", None) or now)
    if shipping_cost is not None:
        try:
            _assign(order, cols, "shipping_cost", round(float(shipping_cost), 2))
        except (TypeError, ValueError):
            pass
    _assign(order, cols, "status", "shipped")
    _stamp_status(order, "shipped", cols)
    _assign(order, cols, "updated_at", now)
    session.add(order)
    session.flush()
    if commit:
        session.commit()
        session.refresh(order)


def _dispatch_one(
    session: Session,
    order: Order,
    *,
    require_confirmed: bool,
    commit: bool = True,
    carrier: str | None = None,
    api_key: str = "",
    api_secret: str = "",
    base_url: str = "",
) -> dict[str, Any]:
    _ = (api_key, api_secret, base_url)
    order_id = str(order.id)
    status_now = _display_status(str(getattr(order, "status", "") or ""))
    city = str(getattr(order, "city", "") or "").strip()
    existing = str(getattr(order, "meta_livraison_code", "") or "").strip()
    if status_now == "cancelled":
        return {"order_id": order_id, "success": False, "tracking": "", "error": "cannot_ship_cancelled"}
    if len(city) < 2:
        return {"order_id": order_id, "success": False, "tracking": "", "error": "invalid_city"}
    if existing:
        return {
            "order_id": order_id,
            "success": True,
            "tracking": existing,
            "error": "",
            "carrier": normalize_carrier(getattr(order, "carrier", None)),
        }
    if require_confirmed and status_now not in ("confirmed", "shipped"):
        return {"order_id": order_id, "success": False, "tracking": "", "error": "order_not_confirmed"}
    if not _has_complete_confirm_details(order):
        return {"order_id": order_id, "success": False, "tracking": "", "error": "confirmation_details_required"}
    carrier_id = normalize_carrier(carrier or getattr(order, "carrier", None))
    adapter = get_carrier(carrier_id)
    if not adapter.is_configured():
        return {
            "order_id": order_id,
            "success": False,
            "tracking": "",
            "error": f"{carrier_id}_not_configured",
            "carrier": carrier_id,
        }
    result = run_sync(adapter.create_shipment(order))
    if not result.get("ok"):
        err = _detail_text(result.get("error") if result.get("error") not in (None, "") else result.get("raw"))
        return {
            "order_id": order_id,
            "success": False,
            "tracking": "",
            "error": err or "shipment_failed",
            "carrier": carrier_id,
        }
    code = str(result.get("tracking_number") or "").strip() or str(order.id).replace("-", "")[:8].upper()
    ticket_url = str(result.get("ticket_url") or "").strip() or None
    billed = extract_quick_billed_fee(result.get("raw") or result) if carrier_id == "quick_livraison" else None
    shipping_cost = resolve_dispatch_shipping_cost(session, order, carrier_id, billed=billed)
    _persist_shipped(session, order, code, ticket_url, commit=commit, carrier=carrier_id, shipping_cost=shipping_cost)
    return {"order_id": order_id, "success": True, "tracking": code, "error": "", "carrier": carrier_id, "shipping_cost": shipping_cost}


def apply_order_update(
    order: Order,
    payload: OrderUpdate | dict[str, Any],
    cols: set[str] | None = None,
    session: Session | None = None,
) -> Order:
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
        city_val = str(data["city"]).strip()[:160]
        if len(city_val) < 2:
            raise HTTPException(status_code=422, detail="invalid_city")
        _assign(order, known, "city", city_val)
        if "shipping_city" not in data:
            official = city_val if is_official_meta_city(city_val) else resolve_meta_city(city_val)
            if official and is_official_meta_city(official):
                _assign(order, known, "shipping_city", official)
                region_id = region_id_for_city(official)
                if region_id:
                    _assign(order, known, "region_id", region_id)
    if "shipping_city" in data:
        shipping = str(data["shipping_city"] or "").strip()[:160] or None
        if shipping and not is_official_meta_city(shipping):
            resolved = resolve_meta_city(shipping)
            if resolved and is_official_meta_city(resolved):
                shipping = resolved
        _assign(order, known, "shipping_city", shipping)
        if shipping:
            region_id = region_id_for_city(shipping)
            if region_id:
                _assign(order, known, "region_id", region_id)
    if "product_slug" in data and data["product_slug"]:
        raw = str(data["product_slug"]).strip()[:64]
        slug = resolve_order_slug(session, raw) if session is not None else raw
        _assign(order, known, "product_slug", slug or order.product_slug)
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
    if "region_id" in data and "shipping_city" not in data:
        _assign(order, known, "region_id", _resolve_region(str(data["region_id"]) if data["region_id"] is not None else None))
    if "carrier" in data and data["carrier"]:
        _assign(order, known, "carrier", normalize_carrier(str(data["carrier"])))
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
    if "assigned_team_member_id" in data:
        member_id = str(data["assigned_team_member_id"] or "").strip()[:64] or "mohammed"
        _assign(order, known, "assigned_team_member_id", member_id)
    _assign(order, known, "updated_at", datetime.now(timezone.utc))
    next_status = _display_status(str(getattr(order, "status", current_status) or current_status))
    if next_status == "confirmed" and current_status != "confirmed" and not _has_complete_confirm_details(order):
        raise HTTPException(status_code=422, detail="confirmation_details_required")
    return order


def _status_filter(value: str):
    if value == "new":
        return Order.status.in_(NEW_EQUIV)
    if value == "shipped":
        return Order.status.in_(("shipped", "in_shipping"))
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
        elif display in ("shipped", "out_of_zone"):
            shipped += 1
        elif display == "delivered":
            delivered += 1
        elif display == "cancelled":
            cancelled += 1
        if display not in ("cancelled", "returned"):
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


@router.get("/analytics/logistics")
def admin_logistics_analytics(
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    return logistics_analytics(session)


@router.get("/tarifs")
def admin_tarifs_lookup(
    search: str = Query(default="", max_length=80),
    limit: int = Query(default=200, ge=1, le=800),
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    return list_lookup_tarifs(session, search=search, limit=limit)


class TarifRatePatch(BaseModel):
    city_name: str | None = Field(default=None, max_length=160)
    pricing_city_id: str | None = Field(default=None, max_length=64)
    meta_city_id: str | None = Field(default=None, max_length=32)
    quick_delivery_price: float | None = Field(default=None, ge=0, le=9999)
    meta_delivery_fee: float | None = Field(default=None, ge=0, le=9999)
    competitor_delivery_price: float | None = Field(default=None, ge=0, le=9999)
    competitor_retour_price: float | None = Field(default=None, ge=0, le=9999)


@router.patch("/tarifs")
def admin_tarifs_patch(
    body: TarifRatePatch,
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    meta_fee = body.meta_delivery_fee if body.meta_delivery_fee is not None else body.competitor_delivery_price
    try:
        return apply_city_rate_patch(
            session,
            pricing_city_id=body.pricing_city_id,
            meta_city_id=body.meta_city_id,
            city_name=body.city_name,
            quick_delivery_price=body.quick_delivery_price,
            meta_delivery_fee=meta_fee,
            competitor_retour_price=body.competitor_retour_price,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/city-tarifs")
def admin_city_tarifs(
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    tarifs = serialize_tarifs(session)
    return {"count": len(tarifs), "tarifs": tarifs, "source": "FES"}


@router.post("/city-tarifs/sync")
def admin_sync_city_tarifs(
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    report = sync_meta_city_tarifs(session)
    session.commit()
    return report


@router.get("/carriers")
def admin_carriers(admin: dict = Depends(get_current_admin)):
    _ = admin
    return {"carriers": carrier_catalog()}


@router.post("/carriers/quick-livraison/sync-cities")
def admin_sync_quick_cities(
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    if not get_carrier("quick_livraison").is_configured():
        raise HTTPException(status_code=400, detail="quick_livraison_not_configured")
    return sync_quick_districts(session)


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
        "orders": [_serialize_order(o, session) for o in orders],
        "cities": [c for c in cities if c],
    }


def _undispatched_empty(error: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "new_orders_count": 0,
        "overdue_orders_count": 0,
        "total_count": 0,
        "new_items": [],
        "overdue_items": [],
        "items": [],
    }
    if error:
        payload["error"] = error
    return payload


def _undispatched_no_tracking():
    return or_(
        col(Order.meta_livraison_code).is_(None),
        Order.meta_livraison_code == "",
    )


def _undispatched_hours(value: datetime | None, now: datetime) -> int:
    if value is None:
        return 0
    stamp = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return max(0, int((now - stamp).total_seconds() // 3600))


def _undispatched_item(order: Order, now: datetime, delayed_from: datetime | None) -> dict[str, Any]:
    compact = str(order.id).replace("-", "")[:6].upper()
    return {
        "id": str(order.id),
        "order_id": str(order.id),
        "code": f"#CFG-{compact}",
        "full_name": order.full_name,
        "client_name": order.full_name,
        "customer_name": order.full_name,
        "phone": order.phone_national or order.phone,
        "phone_national": order.phone_national,
        "city": order.city,
        "address": getattr(order, "address", None),
        "status": _display_status(order.status),
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "confirmed_at": order.confirmed_at.isoformat() if order.confirmed_at else None,
        "hours_delayed": _undispatched_hours(delayed_from or order.confirmed_at or order.created_at, now),
        "hours_ago": _undispatched_hours(order.created_at, now),
        "meta_livraison_code": getattr(order, "meta_livraison_code", None),
    }


@router.get("/orders/undispatched-summary")
def admin_undispatched_summary(
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    try:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=24)
        no_tracking = _undispatched_no_tracking()
        new_statuses = ("pending", "new", "upsell_accepted", "confirmed")
        overdue_where = and_(
            no_tracking,
            Order.status == "confirmed",
            or_(
                Order.confirmed_at <= cutoff,
                and_(col(Order.confirmed_at).is_(None), Order.created_at <= cutoff),
            ),
        )
        new_where = and_(
            no_tracking,
            Order.status.in_(new_statuses),
            Order.created_at >= cutoff,
            or_(
                Order.status != "confirmed",
                and_(
                    Order.status == "confirmed",
                    or_(
                        Order.confirmed_at > cutoff,
                        and_(col(Order.confirmed_at).is_(None), Order.created_at > cutoff),
                    ),
                ),
            ),
        )

        def _count(clause) -> int:
            raw = session.exec(select(func.count(Order.id)).where(clause)).one()
            if isinstance(raw, (tuple, list)):
                return int(raw[0] or 0)
            return int(raw or 0)

        new_count = _count(new_where)
        overdue_count = _count(overdue_where)
        new_rows = session.exec(
            select(Order).where(new_where).order_by(col(Order.created_at).desc()).limit(50)
        ).all()
        overdue_rows = session.exec(
            select(Order)
            .where(overdue_where)
            .order_by(col(Order.confirmed_at).asc(), col(Order.created_at).asc())
            .limit(50)
        ).all()
        overdue_items = [
            _undispatched_item(row, now, row.confirmed_at or row.created_at) for row in overdue_rows
        ]
        new_items = [_undispatched_item(row, now, row.created_at) for row in new_rows]
        return {
            "new_orders_count": new_count,
            "overdue_orders_count": overdue_count,
            "total_count": new_count + overdue_count,
            "new_items": new_items,
            "overdue_items": overdue_items,
            "items": overdue_items,
        }
    except Exception as exc:
        traceback.print_exc()
        return _undispatched_empty(str(exc))


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
    slug = resolve_order_slug(session, str(body.get("product_slug") or "quran"))
    allowed_cross = ("quran", "kids", "music", "educative", "taalim", "extra")
    cross = str(body.get("cross_sell_slug") or body.get("secondary_product") or "").strip() or None
    if cross not in allowed_cross:
        cross = None
    bundle = bool(body.get("bundle_enabled")) and bool(cross)
    secondary_qty = max(1, min(20, int(body.get("secondary_qty") or 1)))
    assigned_team_member_id = str(body.get("assigned_team_member_id") or "mohammed").strip()[:64] or "mohammed"
    address = str(body.get("address") or body.get("full_address") or "").strip() or None
    notes = str(body.get("courier_notes") or body.get("driver_comment") or "").strip() or None
    shipping = str(body.get("shipping_city") or "").strip()[:160] or None
    region_id = region_id_for_city(shipping) if shipping else ""
    if not region_id:
        region_id = _resolve_region(str(body.get("region_id") or body.get("region") or "") or None)
    order_id = uuid4()
    now = datetime.now(timezone.utc)
    order = Order(
        id=order_id,
        full_name=name,
        phone=e164,
        phone_national=to_national(e164),
        city=city,
        shipping_city=shipping,
        product_slug=slug,
        tier_qty=qty,
        tier_price_cents=cents,
        subtotal_cents=cents,
        total_cents=cents,
        status=status_value,
        event_id=f"admin-{order_id}",
        source="admin",
        assigned_team_member_id=assigned_team_member_id,
        updated_at=now,
        address=address,
        quartier=str(body.get("quartier") or "").strip() or None,
        street=str(body.get("street") or "").strip() or None,
        building=str(body.get("building") or "").strip() or None,
        landmark=str(body.get("landmark") or "").strip() or None,
        courier_notes=notes,
        region_id=region_id or None,
        cross_sell_slug=cross if bundle else None,
        bundle_enabled=bundle,
        secondary_qty=secondary_qty if bundle else 1,
    )
    _stamp_status(order, status_value, _order_column_names(session))
    try:
        session.add(order)
        session.commit()
        session.refresh(order)
        return _serialize_order(order, session)
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
        return _serialize_order(created, session)


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
            return _serialize_order(order, session)
        except HTTPException:
            session.rollback()
            raise
        except Exception:
            session.rollback()
            session.execute(
                text("UPDATE orders SET status = CAST(:status AS VARCHAR) WHERE id = CAST(:id AS UUID)"),
                {"status": str(status_value), "id": str(order.id)},
            )
            session.commit()
            order = _load_order(session, str(order.id))
            if not order:
                raise HTTPException(status_code=404, detail="order_not_found")
            return _serialize_order(order, session)
    try:
        apply_order_update(order, body, cols, session)
        session.add(order)
        session.commit()
        session.refresh(order)
        return _serialize_order(order, session)
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        data = body
        name = str(data.get("full_name") or data.get("customer_name") or data.get("fullName") or order.full_name or "").strip()[:160]
        city = str(data.get("city") or data.get("ville") or order.city or "").strip()[:160]
        shipping = data.get("shipping_city")
        if shipping is None:
            shipping = data.get("shippingCity") if "shippingCity" in data else data.get("meta_city")
        if shipping is not None:
            shipping = str(shipping or "").strip()[:160] or None
        else:
            shipping = getattr(order, "shipping_city", None)
            if city and (not shipping or city != order.city):
                official = city if is_official_meta_city(city) else resolve_meta_city(city)
                if official and is_official_meta_city(official):
                    shipping = official
        slug = resolve_order_slug(
            session,
            str(data.get("product_slug") or data.get("primary_product") or data.get("productSlug") or order.product_slug),
        )
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
                      shipping_city = :shipping_city,
                      product_slug = :product_slug,
                      tier_qty = :tier_qty,
                      total_cents = :total_cents,
                      status = CAST(:status AS VARCHAR),
                      updated_at = now()
                    WHERE id = CAST(:id AS UUID)
                    """
                ),
                {
                    "id": str(order.id),
                    "full_name": name or order.full_name,
                    "city": city or order.city,
                    "shipping_city": shipping,
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
        return _serialize_order(order, session)


@router.post("/orders/bulk-livraison")
def admin_bulk_livraison(
    payload: BulkOrderIds,
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    tokens = _bulk_tokens(payload)
    if not tokens:
        raise HTTPException(status_code=422, detail="order_ids_required")
    carrier_id = normalize_carrier(payload.carrier) if payload.carrier else None
    if carrier_id:
        adapter = get_carrier(carrier_id)
        if not adapter.is_configured():
            raise HTTPException(status_code=400, detail=f"{carrier_id}_not_configured")

    results: list[dict[str, Any]] = []
    for token in tokens:
        try:
            with session.begin_nested():
                order = _load_order_or_tracking(session, token)
                if not order:
                    results.append({"order_id": token, "success": False, "tracking": "", "error": "order_not_found"})
                    continue
                results.append(
                    _dispatch_one(
                        session,
                        order,
                        require_confirmed=True,
                        commit=False,
                        carrier=carrier_id,
                    )
                )
            session.commit()
        except Exception as exc:
            traceback.print_exc()
            try:
                session.rollback()
            except Exception:
                pass
            results.append({"order_id": token, "success": False, "tracking": "", "error": str(exc)})
    success_count = sum(1 for row in results if row.get("success"))
    return {
        "success_count": success_count,
        "failed_count": len(results) - success_count,
        "results": results,
    }


@router.post("/orders/sync-tracking")
async def admin_sync_tracking(admin: dict = Depends(get_current_admin)):
    _ = admin
    from app.services.tracking_sync import sync_shipped_orders_async

    try:
        return await sync_shipped_orders_async()
    except Exception as exc:
        print(f"[TRACKING_SYNC_ERROR] {traceback.format_exc()}", flush=True)
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "ok": False,
                "detail": str(exc) or "تعذر تحديث حالات الشحن.",
                "total_checked": 0,
                "updated_count": 0,
                "details": [],
            },
        )


@router.post("/orders/bulk-labels")
def admin_bulk_labels(
    payload: BulkOrderIds,
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    return admin_bulk_labels_pdf(payload, admin, session)


LABEL_NOT_DISPATCHED = "لا يمكن طباعة بوليصة شحن لطلبية لم يتم إرسالها لشركة التوصيل بعد."


def _tracking_code(order: Order) -> str:
    return str(getattr(order, "meta_livraison_code", "") or "").strip()


def _pdf_labels(session: Session, orders: list[Order], filename: str, inline: bool = False) -> Response:
    from app.services.shipping_label import render_label_pdf

    payload = render_label_pdf(orders, load_tarif_index(session))
    disposition = "inline" if inline else "attachment"
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


@router.get("/orders/{order_id}/label-pdf")
def admin_label_pdf(
    order_id: str,
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    order = _load_order(session, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="order_not_found")
    if not _tracking_code(order):
        raise HTTPException(status_code=400, detail=LABEL_NOT_DISPATCHED)
    return _pdf_labels(session, [order], f"label-{_tracking_code(order)}.pdf", inline=True)


@router.post("/orders/bulk-labels-pdf")
def admin_bulk_labels_pdf(
    payload: BulkOrderIds,
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    tokens = _bulk_tokens(payload)
    if not tokens:
        raise HTTPException(status_code=422, detail="order_ids_required")
    ready: list[Order] = []
    seen: set[str] = set()
    for token in tokens:
        order = _load_order_or_tracking(session, token)
        if not order or not _tracking_code(order):
            continue
        oid = str(order.id)
        if oid in seen:
            continue
        seen.add(oid)
        ready.append(order)
    if not ready:
        raise HTTPException(status_code=400, detail=LABEL_NOT_DISPATCHED)
    return _pdf_labels(session, ready, "chifaglow-labels.pdf", inline=True)


@router.post("/orders/manifest")
def admin_manifest(
    payload: BulkOrderIds,
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    tokens = _bulk_tokens(payload)
    if not tokens:
        raise HTTPException(status_code=422, detail="order_ids_required")
    from app.services.manifest import render_manifest_html

    loaded: list[Order] = []
    for token in tokens:
        order = _load_order_or_tracking(session, token)
        if order:
            loaded.append(order)
    html = render_manifest_html(loaded)
    return HTMLResponse(content=html)


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
                        "message": "Ø¬Ù„Ø³Ø© Ø§Ù„Ø£Ø¯Ù…Ù† ØºÙŠØ± ØµØ§Ù„Ø­Ø©. Ø£Ø¹Ø¯ ØªØ³Ø¬ÙŠÙ„ Ø§Ù„Ø¯Ø®ÙˆÙ„." if exc.status_code == 401 else str(exc.detail),
                        "origin": "admin_session",
                        "error": str(exc.detail),
                    },
                    status_code=exc.status_code,
                )

            body: dict[str, Any] = {}
            try:
                raw = await request.body()
                if raw:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        body = parsed
            except Exception:
                body = {}
            carrier = body.get("carrier") if body else None

            order = _load_order(session, order_id)
            if not order:
                return JSONResponse({"success": False, "detail": "order_not_found"}, status_code=404)

            outcome = _dispatch_one(
                session,
                order,
                require_confirmed=False,
                carrier=str(carrier) if carrier else None,
            )
            if not outcome.get("success"):
                detail = outcome.get("error") or "shipment_failed"
                status_code = 404 if detail == "order_not_found" else 400
                return JSONResponse(
                    status_code=status_code,
                    content=jsonable_encoder(
                        {
                            "success": False,
                            "origin": outcome.get("carrier") or "carrier",
                            "detail": detail,
                        }
                    ),
                )
            session.refresh(order)
            return JSONResponse({**_serialize_order(order, session), "success": True})
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


def _prepare_quick_stock_dispatch(order_id: str, body: QuickStockDispatchRequest) -> dict[str, Any] | JSONResponse:
    with Session(engine) as session:
        order = _load_order(session, order_id)
        if not order:
            return JSONResponse(
                status_code=404,
                content={"success": False, "ok": False, "detail": "order_not_found", "message": "الطلبية غير موجودة."},
            )
        city_label = str(getattr(order, "shipping_city", "") or getattr(order, "city", "") or "").strip()
        status_now = _display_status(str(getattr(order, "status", "") or ""))
        if status_now == "cancelled":
            return JSONResponse(
                status_code=400,
                content={"success": False, "ok": False, "detail": "cannot_ship_cancelled", "message": "لا يمكن شحن طلبية ملغاة."},
            )
        if len(city_label) < 2:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "ok": False,
                    "detail": unmapped_city_detail(city_label),
                    "message": unmapped_city_detail(city_label),
                },
            )
        existing = str(getattr(order, "meta_livraison_code", "") or "").strip()
        if existing:
            payload = _serialize_order(order, session)
            payload.update({"success": True, "ok": True, "tracking_number": existing, "code_envoi": existing})
            return JSONResponse(content=payload)
        if not _has_complete_confirm_details(order):
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "ok": False,
                    "detail": "confirmation_details_required",
                    "message": "كمّل معلومات التوصيل قبل الشحن.",
                },
            )
        product = find_product(session, str(getattr(order, "product_slug", "") or ""))
        if not product or not bool(getattr(product, "is_quick_stock", False)):
            return JSONResponse(
                status_code=400,
                content={"success": False, "ok": False, "detail": "not_quick_stock", "message": "هذا المنتج ليس من مخزون Quick."},
            )
        try:
            catalog_quick_id = int(getattr(product, "quick_product_id", None) or 0)
        except (TypeError, ValueError):
            catalog_quick_id = 0
        try:
            requested_id = int(body.product_id or 0)
        except (TypeError, ValueError):
            requested_id = 0
        quick_id = requested_id if requested_id >= 1 else catalog_quick_id
        if quick_id < 1:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "ok": False,
                    "detail": "quick_product_id_missing",
                    "message": "أضف معرف المنتج في كويك من إدارة المنتجات قبل الإرسال من المخزون.",
                },
            )
        qty = int(body.quantity or 1)
        if qty < 1:
            qty = int(getattr(order, "tier_qty", 1) or 1) or 1
        return {
            "order": _snapshot_order(order),
            "order_id": str(order.id),
            "product_slug": str(getattr(order, "product_slug", "") or ""),
            "quick_id": quick_id,
            "qty": qty,
            "city_label": city_label,
        }


def _finalize_quick_stock_dispatch(
    order_id: str,
    product_slug: str,
    tracking: str,
    ticket: str | None,
    qty: int,
    result: dict[str, Any],
) -> dict[str, Any] | JSONResponse:
    with Session(engine) as session:
        order = _load_order(session, order_id)
        if not order:
            return JSONResponse(
                status_code=404,
                content={"success": False, "ok": False, "detail": "order_not_found", "message": "الطلبية غير موجودة."},
            )
        product = find_product(session, product_slug)
        if product:
            product.stock_quantity = max(0, int(getattr(product, "stock_quantity", 0) or 0) - qty)
            session.add(product)
        billed = extract_quick_billed_fee(result.get("raw") or result)
        shipping_cost = resolve_dispatch_shipping_cost(session, order, "quick_livraison", billed=billed)
        _persist_shipped(session, order, tracking, ticket, carrier="quick_livraison", shipping_cost=shipping_cost)
        session.refresh(order)
        payload = _serialize_order(order, session)
        payload.update(
            {
                "ok": True,
                "success": True,
                "tracking_number": tracking,
                "code_envoi": tracking,
                "shipping_cost": shipping_cost,
                "message": result.get("message") or "Colis ajouté avec succès.",
                "quick_product_id": result.get("quick_product_id"),
                "quantity": result.get("quantity") or qty,
                "stock_quantity": int(getattr(product, "stock_quantity", 0) or 0) if product else 0,
            }
        )
        return payload


@router.post("/orders/{order_id}/dispatch-quick-stock")
async def admin_dispatch_quick_stock(
    order_id: str,
    body: QuickStockDispatchRequest = Body(default_factory=QuickStockDispatchRequest),
    admin: dict = Depends(get_current_admin),
):
    _ = admin
    city_label = ""
    try:
        prepared = _prepare_quick_stock_dispatch(order_id, body)
        if isinstance(prepared, JSONResponse):
            return prepared
        city_label = str(prepared.get("city_label") or "")
        quick_id = int(prepared["quick_id"])
        qty = int(prepared["qty"])
        result = await create_quick_stock_order(prepared["order"], quick_id, qty)
        if not result.get("success"):
            city_label = str(result.get("city") or city_label)
            error_code = str(result.get("error") or "")
            if error_code == "quick_district_not_mapped":
                detail = str(result.get("detail") or unmapped_city_detail(city_label))
            else:
                detail = str(result.get("detail") or result.get("message") or error_code or "quick_stock_failed")
            status_code = int(result.get("status_code") or 400)
            if status_code >= 500:
                status_code = 400
            return JSONResponse(
                status_code=status_code,
                content=jsonable_encoder(
                    {
                        "success": False,
                        "ok": False,
                        "origin": "quick_livraison",
                        "detail": detail,
                        "message": detail,
                        "city": city_label,
                        "raw": result.get("raw"),
                        "quick_product_id": result.get("quick_product_id") or quick_id,
                        "quantity": result.get("quantity") or qty,
                    }
                ),
            )
        tracking = str(result.get("tracking_number") or "").strip()
        if not tracking:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "ok": False,
                    "origin": "quick_livraison",
                    "detail": "Quick Livraison لم تُرجع كود التتبع.",
                    "message": "Quick Livraison لم تُرجع كود التتبع.",
                },
            )
        ticket = str(result.get("ticket_url") or "").strip() or None
        finalized = _finalize_quick_stock_dispatch(
            str(prepared["order_id"]),
            str(prepared["product_slug"]),
            tracking,
            ticket,
            qty,
            result,
        )
        return finalized
    except HTTPException as exc:
        if exc.status_code < 500:
            return JSONResponse(
                status_code=exc.status_code,
                content={"success": False, "ok": False, "detail": exc.detail, "message": str(exc.detail)},
            )
        print(f"[QUICK_STOCK_ERROR] {traceback.format_exc()}", flush=True)
        detail = str(exc.detail) if exc.detail else unmapped_city_detail(city_label)
        return JSONResponse(status_code=400, content={"success": False, "ok": False, "detail": detail, "message": detail, "city": city_label})
    except Exception as exc:
        print(f"[QUICK_STOCK_ERROR] {traceback.format_exc()}", flush=True)
        detail = str(exc) or unmapped_city_detail(city_label)
        folded = detail.casefold()
        if "timeout" in folded or "timed out" in folded:
            detail = "تعذر الاتصال بـ Quick Livraison (انتهت المهلة). حاول مرة أخرى."
        return JSONResponse(
            status_code=400,
            content={"success": False, "ok": False, "detail": detail, "message": detail, "city": city_label},
        )
