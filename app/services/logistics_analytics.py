from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlmodel import Session, select

from app.models import Order
from app.services.city_tarifs import (
    DEFAULT_DELIVERY_FEE,
    DEFAULT_REFUSAL_FEE,
    DEFAULT_RETURN_FEE,
    load_tarif_index,
)
from app.services.pricing import cents_to_mad
from app.services.regions import REGION_ID_TO_NAME, REGION_IDS, region_id_for_city

NEW_EQUIV = ("pending", "upsell_accepted", "new")
ALLOWED_STATUSES = ("new", "confirmed", "shipped", "delivered", "returned", "cancelled")
TOP_CITIES_LIMIT = 5


def _display_status(raw: str) -> str:
    value = (raw or "pending").strip()
    if value in NEW_EQUIV:
        return "new"
    if value == "in_shipping":
        return "shipped"
    if value in ALLOWED_STATUSES:
        return value
    return "new"


def _rate(delivered: int, returned: int, cancelled: int) -> float:
    closed = delivered + returned + cancelled
    if not closed:
        return 0.0
    return round((delivered / closed) * 100, 1)


def _resolve_region(region_id: str | None, shipping_city: str | None, city: str | None) -> str:
    rid = (region_id or "").strip().upper()
    if rid in REGION_IDS:
        return rid
    for candidate in (shipping_city, city):
        mapped = region_id_for_city(candidate or "")
        if mapped in REGION_IDS:
            return mapped
    return ""


def _city_label(shipping_city: str | None, city: str | None) -> str:
    official = (shipping_city or "").strip()
    if official:
        return official
    return (city or "").strip()


def _empty_region(region_id: str) -> dict[str, Any]:
    return {
        "region_id": region_id,
        "name": REGION_ID_TO_NAME.get(region_id, region_id),
        "total_orders": 0,
        "delivered": 0,
        "returned": 0,
        "cancelled": 0,
        "in_transit": 0,
        "delivery_rate": 0.0,
        "cod_generated": 0.0,
        "top_cities": [],
        "_cities": defaultdict(int),
        "_cod_cents": 0,
    }


def _finalize_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    cities = bucket.pop("_cities")
    cod_cents = int(bucket.pop("_cod_cents") or 0)
    ranked = sorted(cities.items(), key=lambda item: (-item[1], item[0].lower()))[:TOP_CITIES_LIMIT]
    bucket["top_cities"] = [{"city": name, "count": count} for name, count in ranked]
    bucket["cod_generated"] = cents_to_mad(cod_cents)
    bucket["delivery_rate"] = _rate(bucket["delivered"], bucket["returned"], bucket["cancelled"])
    return bucket


def logistics_analytics(session: Session) -> dict[str, Any]:
    tarifs = load_tarif_index(session)
    rows = session.exec(
        select(Order.status, Order.total_cents, Order.region_id, Order.city, Order.shipping_city)
    ).all()

    delivered_cents = in_transit_cents = 0
    delivered_count = in_transit_count = returned_count = cancelled_count = 0
    delivery_costs = refusal_costs = return_costs = 0.0
    mapped_fee_orders = unmapped_fee_orders = 0
    regions = {rid: _empty_region(rid) for rid in REGION_IDS}
    unmapped = _empty_region("")
    unmapped["name"] = "غير محددة"

    for raw_status, cents, region_id, city, shipping_city in rows:
        display = _display_status(raw_status or "pending")
        amount = int(cents or 0)
        delivery_fee, refusal_fee, return_fee = tarifs.fees_for(shipping_city, city)
        hit = tarifs.find(shipping_city, city)
        if display in ("delivered", "returned", "cancelled"):
            if hit:
                mapped_fee_orders += 1
            else:
                unmapped_fee_orders += 1
        if display == "delivered":
            delivered_count += 1
            delivered_cents += amount
            delivery_costs += delivery_fee
        elif display == "shipped":
            in_transit_count += 1
            in_transit_cents += amount
        elif display == "returned":
            returned_count += 1
            return_costs += return_fee
        elif display == "cancelled":
            cancelled_count += 1
            refusal_costs += refusal_fee

        rid = _resolve_region(region_id, shipping_city, city)
        bucket = regions.get(rid) or unmapped
        bucket["total_orders"] += 1
        if display == "delivered":
            bucket["delivered"] += 1
            bucket["_cod_cents"] += amount
        elif display == "returned":
            bucket["returned"] += 1
        elif display == "cancelled":
            bucket["cancelled"] += 1
        elif display == "shipped":
            bucket["in_transit"] += 1
        city_name = _city_label(shipping_city, city)
        if city_name:
            bucket["_cities"][city_name] += 1

    shipping_costs = round(delivery_costs + refusal_costs + return_costs, 2)
    delivered_amount = cents_to_mad(delivered_cents)
    in_transit_amount = cents_to_mad(in_transit_cents)
    closed = delivered_count + returned_count + cancelled_count

    return {
        "currency": "MAD",
        "delivery_fee": DEFAULT_DELIVERY_FEE,
        "refusal_fee": DEFAULT_REFUSAL_FEE,
        "return_fee": DEFAULT_RETURN_FEE,
        "financial": {
            "total_delivered_amount": delivered_amount,
            "in_transit_amount": in_transit_amount,
            "delivered_count": delivered_count,
            "in_transit_count": in_transit_count,
            "returned_count": returned_count,
            "cancelled_count": cancelled_count,
            "delivery_costs": round(delivery_costs, 2),
            "refusal_costs": round(refusal_costs, 2),
            "return_costs": round(return_costs, 2),
            "estimated_shipping_costs": shipping_costs,
            "net_cash_due": round(delivered_amount - shipping_costs, 2),
            "mapped_fee_orders": mapped_fee_orders,
            "unmapped_fee_orders": unmapped_fee_orders,
        },
        "delivery_rate": _rate(delivered_count, returned_count, cancelled_count),
        "delivery_rate_denominator": closed,
        "regions": [_finalize_bucket(regions[rid]) for rid in REGION_IDS],
        "unmapped": _finalize_bucket(unmapped),
    }
