from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import or_
from sqlmodel import Session, col, select

from app.models import CityTarif, DeliveryCity, utcnow
from app.services.city_tarifs import (
    DEFAULT_DELIVERY_FEE,
    DEFAULT_REFUSAL_FEE,
    DEFAULT_RETURN_FEE,
    city_match_keys,
    fold_city,
    hub_code,
)
from app.services.meta_livraison_cities import resolve_meta_city
from app.services.quick_pricing import (
    DEFAULT_COMPETITOR_NAME,
    DEFAULT_COMPETITOR_RETOUR,
    META_COMPETITOR_NAME,
    QUICK_REFUS_PRICE,
    QUICK_RETOUR_PRICE,
    _arabic_name,
    _money,
    _search_blob,
)
from app.utils.regions import REGION_ID_TO_NAME, get_region_for_city, region_id_for_city

QUICK_BILLED_KEYS = {
    "delivery_price",
    "delivery_price_mad",
    "delivery_fee",
    "delivery_cost",
    "deliverycost",
    "shipping_cost",
    "shipping_fee",
    "frais_livraison",
    "tarif_livraison",
    "price_delivery",
    "livraison_price",
    "billed_price",
    "deliveryprice",
    "crbt_delivery",
}


def _candidate_names(*names: str | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        text = str(name or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        official = resolve_meta_city(text)
        if official and official not in seen:
            seen.add(official)
            out.append(official)
    return out


def _index_rows(rows: list[Any], *name_attrs: str) -> dict[str, Any]:
    index: dict[str, Any] = {}
    for row in rows:
        for attr in name_attrs:
            value = str(getattr(row, attr, "") or "").strip()
            for key in city_match_keys(value):
                index.setdefault(key, row)
        city_key = str(getattr(row, "city_key", "") or "").strip()
        if city_key:
            index.setdefault(city_key, row)
            index.setdefault(city_key.replace(" ", ""), row)
    return index


def _find_indexed(index: dict[str, Any], *names: str | None) -> Any | None:
    for name in _candidate_names(*names):
        for key in city_match_keys(name):
            hit = index.get(key)
            if hit is not None:
                return hit
    return None


def extract_quick_billed_fee(payload: Any, *, depth: int = 0) -> float | None:
    """Pull the billed delivery fee from a Quick store JSON payload, never the COD amount."""
    if depth > 4 or payload is None:
        return None
    if isinstance(payload, list):
        for item in payload:
            found = extract_quick_billed_fee(item, depth=depth + 1)
            if found is not None:
                return found
        return None
    if not isinstance(payload, dict):
        return None
    for key, value in payload.items():
        folded = fold_city(str(key)).replace(" ", "")
        if folded in QUICK_BILLED_KEYS or folded.replace("_", "") in QUICK_BILLED_KEYS:
            amount = _money(value, -1)
            if amount >= 0:
                return amount
    for nested_key in ("data", "colis", "parcel", "delivery", "result"):
        nested = payload.get(nested_key)
        found = extract_quick_billed_fee(nested, depth=depth + 1)
        if found is not None:
            return found
    return None


def lookup_quick_city(session: Session, *names: str | None) -> DeliveryCity | None:
    rows = list(session.exec(select(DeliveryCity)).all())
    return _find_indexed(_index_rows(rows, "city_name", "city_name_ar"), *names)


def lookup_meta_city(session: Session, *names: str | None) -> CityTarif | None:
    rows = list(session.exec(select(CityTarif)).all())
    return _find_indexed(_index_rows(rows, "city_name"), *names)


def lookup_quick_delivery_price(session: Session, *names: str | None) -> float | None:
    hit = lookup_quick_city(session, *names)
    if hit is None:
        return None
    return _money(hit.quick_delivery_price)


def lookup_meta_delivery_fee(session: Session, *names: str | None) -> float:
    hit = lookup_meta_city(session, *names)
    if hit is None:
        return DEFAULT_DELIVERY_FEE
    return _money(hit.delivery_fee, DEFAULT_DELIVERY_FEE)


def resolve_dispatch_shipping_cost(
    session: Session,
    order: Any,
    carrier: str,
    *,
    billed: float | None = None,
) -> float:
    if billed is not None:
        amount = _money(billed, -1)
        if amount >= 0:
            return amount
    names = (
        getattr(order, "shipping_city", None),
        getattr(order, "city", None),
    )
    if carrier == "quick_livraison":
        quick = lookup_quick_delivery_price(session, *names)
        if quick is not None:
            return quick
    return lookup_meta_delivery_fee(session, *names)


def _region_fields(*names: str | None) -> tuple[str, str]:
    for name in _candidate_names(*names):
        region_id = region_id_for_city(name)
        if region_id:
            return region_id, REGION_ID_TO_NAME.get(region_id, get_region_for_city(name))
        region_name = get_region_for_city(name)
        if region_name and region_name != "غير محددة":
            return region_id_for_city(name), region_name
    return "", "غير محددة"


def _serialize_merged(
    *,
    city_name: str,
    city_name_ar: str,
    quick: DeliveryCity | None,
    meta: CityTarif | None,
    lookup_id: int,
) -> dict[str, Any]:
    region_id, region_name = _region_fields(
        city_name,
        getattr(quick, "city_name", None),
        getattr(meta, "city_name", None),
    )
    quick_price = None if quick is None else _money(quick.quick_delivery_price)
    meta_price = None if meta is None else _money(meta.delivery_fee, DEFAULT_DELIVERY_FEE)
    competitor_price = None
    if quick is not None and quick.competitor_delivery_price is not None:
        competitor_price = _money(quick.competitor_delivery_price)
    if meta_price is None:
        meta_price = competitor_price
    elif competitor_price is not None:
        meta_price = competitor_price
    cheaper = "unknown"
    savings = None
    if quick_price is not None and meta_price is not None:
        savings = round(meta_price - quick_price, 2)
        if savings > 0:
            cheaper = "quick"
        elif savings < 0:
            cheaper = "meta"
        else:
            cheaper = "tie"
    arabic = city_name_ar or _arabic_name(city_name, getattr(meta, "city_name", "") if meta else "")
    return {
        "id": lookup_id,
        "pricing_city_id": str(quick.id) if quick is not None else None,
        "meta_city_id": str(meta.meta_city_id) if meta is not None else None,
        "city_key": (quick.city_key if quick is not None else fold_city(city_name)),
        "city_name": city_name,
        "city_name_ar": arabic,
        "hub_name": hub_code(getattr(meta, "hub_name", None)) if meta is not None else "",
        "region_id": region_id or None,
        "region": region_name,
        "delivery_delay": (getattr(quick, "delivery_delay", None) or "").strip() or None,
        "quick_delivery_price": quick_price,
        "quick_retour_price": QUICK_RETOUR_PRICE,
        "quick_refus_price": QUICK_REFUS_PRICE,
        "meta_delivery_fee": meta_price,
        "meta_refusal_fee": _money(getattr(meta, "refusal_fee", None), DEFAULT_REFUSAL_FEE) if meta is not None else None,
        "meta_return_fee": _money(getattr(meta, "return_fee", None), DEFAULT_RETURN_FEE) if meta is not None else None,
        "delivery_fee": meta_price if meta_price is not None else (quick_price or DEFAULT_DELIVERY_FEE),
        "refusal_fee": _money(getattr(meta, "refusal_fee", None), DEFAULT_REFUSAL_FEE) if meta is not None else DEFAULT_REFUSAL_FEE,
        "return_fee": _money(getattr(meta, "return_fee", None), DEFAULT_RETURN_FEE) if meta is not None else DEFAULT_RETURN_FEE,
        "competitor_name": META_COMPETITOR_NAME if (meta is not None or (quick and quick.competitor_name)) else DEFAULT_COMPETITOR_NAME,
        "competitor_delivery_price": meta_price,
        "competitor_retour_price": _money(getattr(quick, "competitor_retour_price", None), DEFAULT_COMPETITOR_RETOUR),
        "quick_covered": quick is not None,
        "meta_covered": meta is not None or (quick is not None and quick.competitor_delivery_price is not None),
        "quick_total": quick_price,
        "competitor_total": None if meta_price is None else round(meta_price + DEFAULT_COMPETITOR_RETOUR, 2),
        "savings": savings,
        "cheaper": cheaper if cheaper != "meta" else "competitor",
    }


def _lookup_id(meta: CityTarif | None, quick: DeliveryCity | None, fallback: int) -> int:
    if meta is not None:
        raw = str(meta.meta_city_id or "").strip()
        if raw.isdigit():
            return int(raw)
        return int(meta.id.int % 2_147_483_647)
    if quick is not None:
        return int(quick.id.int % 2_147_483_647)
    return fallback


def list_carrier_city_rates(session: Session, search: str = "", limit: int = 200) -> list[dict[str, Any]]:
    cap = max(1, min(int(limit or 200), 800))
    needle = (search or "").strip()
    meta_stmt = select(CityTarif)
    quick_stmt = select(DeliveryCity)
    if needle:
        like = f"%{needle}%"
        meta_stmt = meta_stmt.where(
            or_(col(CityTarif.city_name).ilike(like), col(CityTarif.hub_name).ilike(like))
        )
        quick_stmt = quick_stmt.where(
            or_(
                col(DeliveryCity.city_name).ilike(like),
                col(DeliveryCity.city_name_ar).ilike(like),
                col(DeliveryCity.search_blob).ilike(like),
            )
        )
    meta_rows = list(session.exec(meta_stmt).all())
    quick_rows = list(session.exec(quick_stmt).all())
    meta_index = _index_rows(meta_rows, "city_name")
    quick_index = _index_rows(quick_rows, "city_name", "city_name_ar")

    used_quick: set[str] = set()
    used_meta: set[str] = set()
    merged: list[dict[str, Any]] = []

    def mark(quick: DeliveryCity | None, meta: CityTarif | None) -> None:
        if quick is not None:
            used_quick.add(str(quick.id))
        if meta is not None:
            used_meta.add(str(meta.id))

    for quick in sorted(quick_rows, key=lambda row: (row.city_name or "").casefold()):
        meta = _find_indexed(meta_index, quick.city_name, quick.city_name_ar)
        mark(quick, meta)
        merged.append(
            _serialize_merged(
                city_name=quick.city_name,
                city_name_ar=quick.city_name_ar or "",
                quick=quick,
                meta=meta,
                lookup_id=_lookup_id(meta, quick, len(merged) + 1),
            )
        )

    for meta in sorted(meta_rows, key=lambda row: (row.city_name or "").casefold()):
        if str(meta.id) in used_meta:
            continue
        quick = _find_indexed(quick_index, meta.city_name)
        if quick is not None and str(quick.id) in used_quick:
            continue
        mark(quick, meta)
        merged.append(
            _serialize_merged(
                city_name=meta.city_name,
                city_name_ar=_arabic_name(meta.city_name, meta.city_name),
                quick=quick,
                meta=meta,
                lookup_id=_lookup_id(meta, quick, len(merged) + 1),
            )
        )

    merged.sort(key=lambda row: str(row.get("city_name") or "").casefold())
    return merged[:cap]


def _ensure_delivery_city(session: Session, city_name: str, existing: DeliveryCity | None = None) -> DeliveryCity:
    if existing is not None:
        return existing
    city_key = fold_city(city_name)
    row = session.exec(select(DeliveryCity).where(DeliveryCity.city_key == city_key)).first()
    if row is not None:
        return row
    arabic = _arabic_name(city_name)
    row = DeliveryCity(
        city_key=city_key or city_name.casefold()[:180],
        city_name=city_name[:160],
        city_name_ar=arabic,
        search_blob=_search_blob(city_name, arabic, city_key),
        competitor_name=META_COMPETITOR_NAME,
        competitor_retour_price=DEFAULT_COMPETITOR_RETOUR,
    )
    session.add(row)
    session.flush()
    return row


def apply_city_rate_patch(
    session: Session,
    *,
    pricing_city_id: UUID | str | None = None,
    meta_city_id: str | None = None,
    city_name: str | None = None,
    quick_delivery_price: float | None = None,
    meta_delivery_fee: float | None = None,
    competitor_retour_price: float | None = None,
) -> dict[str, Any]:
    quick: DeliveryCity | None = None
    meta: CityTarif | None = None
    if pricing_city_id:
        try:
            uid = pricing_city_id if isinstance(pricing_city_id, UUID) else UUID(str(pricing_city_id))
        except (TypeError, ValueError):
            uid = None
        if uid is not None:
            quick = session.exec(select(DeliveryCity).where(DeliveryCity.id == uid)).first()
    if meta_city_id:
        meta = session.exec(select(CityTarif).where(CityTarif.meta_city_id == str(meta_city_id).strip())).first()
    names = [city_name, getattr(quick, "city_name", None), getattr(meta, "city_name", None)]
    if quick is None:
        quick = lookup_quick_city(session, *names)
    if meta is None:
        meta = lookup_meta_city(session, *names)
    label = str(city_name or getattr(quick, "city_name", "") or getattr(meta, "city_name", "") or "").strip()
    if not label:
        raise ValueError("city_not_found")

    if quick_delivery_price is not None:
        quick = _ensure_delivery_city(session, label, quick)
        quick.quick_delivery_price = _money(quick_delivery_price)
        quick.quick_retour_price = QUICK_RETOUR_PRICE
        quick.quick_refus_price = QUICK_REFUS_PRICE
        quick.search_blob = _search_blob(quick.city_name, quick.city_name_ar, quick.city_key)
        quick.updated_at = utcnow()
        session.add(quick)

    if meta_delivery_fee is not None:
        fee = _money(meta_delivery_fee, DEFAULT_DELIVERY_FEE)
        if meta is not None:
            meta.delivery_fee = fee
            meta.updated_at = utcnow()
            session.add(meta)
        quick = _ensure_delivery_city(session, label, quick)
        quick.competitor_delivery_price = fee
        quick.competitor_name = META_COMPETITOR_NAME
        quick.updated_at = utcnow()
        session.add(quick)

    if competitor_retour_price is not None:
        quick = _ensure_delivery_city(session, label, quick)
        quick.competitor_retour_price = _money(competitor_retour_price, DEFAULT_COMPETITOR_RETOUR)
        quick.updated_at = utcnow()
        session.add(quick)

    session.commit()
    if quick is not None:
        session.refresh(quick)
    if meta is not None:
        session.refresh(meta)
    return _serialize_merged(
        city_name=label,
        city_name_ar=getattr(quick, "city_name_ar", "") or "",
        quick=quick,
        meta=meta,
        lookup_id=_lookup_id(meta, quick, 0),
    )
