from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from sqlmodel import Session

from app.core.config import QUICK_LIVRAISON_API_KEY
from app.services.carriers.quick import QUICK_HTTP_TIMEOUT, canonical_quick_tracking, quick_client_code
from app.services.city_tarifs import city_match_keys, fold_city
from app.services.meta_livraison_cities import resolve_meta_city
from app.utils.regions import is_region_label

log = logging.getLogger(__name__)

QUICK_STOCK_STORE_URL = "https://clients.quicklivraison.ma/api/deliveries/store"
QUICK_STOCK_PRODUCT_KH01 = 6005
QUICK_API_KEY_FALLBACK = "6sD6fVFImLf0SyE2pzBMdOuiNqUHEJyE"
CASABLANCA_DISTRICT_ID = 43
BIR_JDID_DISTRICT_ID = 674
LAAYOUNE_DISTRICT_ID = 307

QUICK_CITIES = {
    "casablanca": CASABLANCA_DISTRICT_ID,
    "casa": CASABLANCA_DISTRICT_ID,
    "الدار البيضاء": CASABLANCA_DISTRICT_ID,
    "bir jdid": BIR_JDID_DISTRICT_ID,
    "birjdid": BIR_JDID_DISTRICT_ID,
    "ber jdid": BIR_JDID_DISTRICT_ID,
    "berjdid": BIR_JDID_DISTRICT_ID,
    "bir jedid": BIR_JDID_DISTRICT_ID,
    "بير الجديد": BIR_JDID_DISTRICT_ID,
    "laayoune": LAAYOUNE_DISTRICT_ID,
    "laayoune sahara": LAAYOUNE_DISTRICT_ID,
    "العيون": LAAYOUNE_DISTRICT_ID,
    "marrakech": 49,
    "مراكش": 49,
    "agadir": 37,
    "أكادير": 37,
    "rabat": 55,
    "الرباط": 55,
    "fes": 577,
    "فاس": 577,
    "tanger": 103,
    "طنجة": 103,
    "meknes": 547,
    "مكناس": 547,
    "oujda": 67,
    "وجدة": 67,
    "kenitra": 1604,
    "القنيطرة": 1604,
    "tetouan": 133,
    "تطوان": 133,
    "sale": 229,
    "سلا": 229,
    "temara": 253,
    "تمارة": 253,
    "el jadida": 469,
    "الجديدة": 469,
    "nador": 97,
    "الناظور": 97,
    "berrchid": 541,
    "برشيد": 541,
    "settat": 680,
    "سطات": 680,
    "mohammedia": 481,
    "المحمدية": 481,
    "safi": 427,
    "آسفي": 427,
    "beni mellal": 313,
    "بني ملال": 313,
    "khemisset": 1646,
    "الخميسات": 1646,
    "driouch": 1484,
    "الدريوش": 1484,
}


def _index_quick_cities(cities: dict[str, int]) -> dict[str, int]:
    index: dict[str, int] = {}
    for key, val in cities.items():
        folded = fold_city(key)
        if not folded:
            continue
        index[folded] = val
        index[folded.replace(" ", "")] = val
    return index


_QUICK_CITY_INDEX = _index_quick_cities(QUICK_CITIES)


def _api_key() -> str:
    return (QUICK_LIVRAISON_API_KEY or QUICK_API_KEY_FALLBACK).strip() or QUICK_API_KEY_FALLBACK


def resolve_district_id(city_name: str) -> int | None:
    """Exact folded match against known Quick city ids. Never substring, never a silent Casablanca fallback."""
    if is_region_label(city_name):
        return None
    for key in city_match_keys(city_name):
        found = _QUICK_CITY_INDEX.get(key)
        if found:
            return found
    official = resolve_meta_city(city_name)
    if official and official != city_name and not is_region_label(official):
        for key in city_match_keys(official):
            found = _QUICK_CITY_INDEX.get(key)
            if found:
                return found
    return None


def official_city_candidates(order: Any) -> list[str]:
    """Prefer the official selected city (`shipping_city`), then typed `city`. Skip region names."""
    from app.services.carriers.quick import _candidate_city_names

    return _candidate_city_names(order)


def official_city_label(order: Any) -> str:
    names = official_city_candidates(order)
    return names[0] if names else ""


def unmapped_city_detail(city_label: str) -> str:
    label = (city_label or "").strip() or "غير محددة"
    return f"المدينة غير مطابقة في نظام Quick Livraison: {label}"


def _lookup_static_district(order: Any) -> int | None:
    for name in official_city_candidates(order):
        found = resolve_district_id(name)
        if found:
            return found
    return None


async def _lookup_live_district(order: Any, session: Session | None = None) -> int | None:
    from app.services.carriers.quick import _candidate_city_names, _district_from_mapping, cached_city_mapping

    _ = session
    mapping = await cached_city_mapping()
    return _district_from_mapping(mapping, _candidate_city_names(order))


def clean_moroccan_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("212"):
        digits = "0" + digits[3:]
    elif not digits.startswith("0") and len(digits) == 9:
        digits = "0" + digits
    return digits[-10:]


def _customer_name(order: Any) -> str:
    return str(
        getattr(order, "customer_name", None) or getattr(order, "full_name", "") or ""
    ).strip() or "عميل متجر"


def _cod_amount(order: Any) -> float:
    if getattr(order, "total_cents", None) is not None:
        try:
            return round(float(order.total_cents) / 100.0, 2)
        except (TypeError, ValueError):
            pass
    for attr in ("total_price", "price", "total_mad"):
        raw = getattr(order, attr, None)
        if raw in (None, ""):
            continue
        try:
            return round(float(raw), 2)
        except (TypeError, ValueError):
            continue
    return 0.0


def _address(order: Any) -> str:
    stored = str(getattr(order, "address", None) or "").strip()
    city = official_city_label(order) or str(getattr(order, "city", "") or "").strip()
    if stored:
        return stored
    bits = [
        str(getattr(order, field, "") or "").strip()
        for field in ("quartier", "street", "building", "landmark")
    ]
    composed = "، ".join(part for part in bits if part)
    if composed:
        return composed
    return f"مدينة {city}" if city else "Maroc"


def _phone(order: Any) -> str:
    return clean_moroccan_phone(
        str(getattr(order, "phone_national", None) or getattr(order, "phone", "") or "")
    )


def _error_text(data: Any, fallback: str = "") -> str:
    if isinstance(data, dict):
        for key in ("message", "error", "detail", "msg"):
            value = data.get(key)
            if value not in (None, "", False, True):
                return str(value)
        errors = data.get("errors")
        if isinstance(errors, dict):
            parts = [f"{field}: {msgs}" for field, msgs in errors.items() if msgs not in (None, "")]
            if parts:
                return "; ".join(parts)
        success = data.get("success")
        if isinstance(success, str) and success.strip():
            return success
    if data not in (None, ""):
        return str(data)
    return fallback or "quick_stock_failed"


async def create_quick_stock_order(
    order: Any,
    product_id: int,
    quantity: int = 1,
    session: Session | None = None,
) -> dict[str, Any]:
    """Create a Quick Livraison parcel from warehouse stock for the given Quick product ID."""
    _ = session
    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        return {"success": False, "ok": False, "error": "quick_product_id_missing", "status_code": 400}
    if product_id < 1:
        return {"success": False, "ok": False, "error": "quick_product_id_missing", "status_code": 400}
    try:
        quantity = int(quantity or 1)
    except (TypeError, ValueError):
        quantity = 1
    if quantity < 1:
        quantity = 1

    city_label = official_city_label(order)
    try:
        candidates = official_city_candidates(order)
        district_id = _lookup_static_district(order)
        if not district_id:
            try:
                district_id = await _lookup_live_district(order)
            except httpx.TimeoutException:
                detail = "تعذر الاتصال بـ Quick Livraison (انتهت المهلة). حاول مرة أخرى."
                log.warning("Quick getCityIDs timed out city=%r", city_label)
                return {
                    "success": False,
                    "ok": False,
                    "error": "quick_timeout",
                    "detail": detail,
                    "message": detail,
                    "status_code": 400,
                    "city": city_label,
                }
            except Exception as exc:
                log.warning(
                    "Quick city lookup failed; will not fall back to Casablanca. city=%r shipping_city=%r city_field=%r err=%s",
                    city_label,
                    getattr(order, "shipping_city", None),
                    getattr(order, "city", None),
                    exc,
                )
        if not district_id:
            log.warning(
                "Quick district not mapped; refusing silent Casablanca fallback. city=%r candidates=%r shipping_city=%r city_field=%r region_id=%r",
                city_label,
                candidates,
                getattr(order, "shipping_city", None),
                getattr(order, "city", None),
                getattr(order, "region_id", None),
            )
            detail = unmapped_city_detail(city_label)
            return {
                "success": False,
                "ok": False,
                "error": "quick_district_not_mapped",
                "detail": detail,
                "message": detail,
                "status_code": 400,
                "city": city_label,
                "candidates": candidates,
            }
        log.info(
            "Quick stock dispatch city=%r district_id=%s candidates=%r",
            city_label,
            district_id,
            candidates,
        )
        phone = _phone(order)
        cfg_code = quick_client_code(order)
        payload = {
            "api_key": _api_key(),
            "district_id": district_id,
            "name": _customer_name(order),
            "amount": _cod_amount(order),
            "phone": phone,
            "address": _address(order),
            "code": cfg_code,
            "note": str(getattr(order, "courier_notes", "") or ""),
            "open": False,
            "received_quantity": {str(product_id): int(quantity)},
        }

        try:
            async with httpx.AsyncClient(timeout=QUICK_HTTP_TIMEOUT, follow_redirects=True) as client:
                res = await client.post(
                    QUICK_STOCK_STORE_URL,
                    json=payload,
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                )
        except httpx.TimeoutException:
            detail = "تعذر الاتصال بـ Quick Livraison (انتهت المهلة). حاول مرة أخرى."
            return {
                "success": False,
                "ok": False,
                "error": "quick_timeout",
                "detail": detail,
                "message": detail,
                "status_code": 400,
                "city": city_label,
            }
        except httpx.HTTPError as exc:
            detail = str(exc) or "تعذر الاتصال بـ Quick Livraison."
            return {
                "success": False,
                "ok": False,
                "error": "quick_stock_failed",
                "detail": detail,
                "message": detail,
                "status_code": 400,
                "city": city_label,
            }

        try:
            data = res.json()
        except Exception:
            data = {"text": res.text}

        tracking = ""
        if isinstance(data, dict):
            tracking = str(data.get("code") or data.get("reference") or data.get("tracking_number") or "").strip()
        tracking = canonical_quick_tracking(tracking, cfg_code)

        if res.status_code in (200, 201) and tracking:
            billed = None
            if isinstance(data, dict):
                from app.services.carrier_rates import extract_quick_billed_fee

                billed = extract_quick_billed_fee(data)
            return {
                "success": True,
                "ok": True,
                "tracking_number": tracking,
                "message": data.get("success", "Colis ajouté avec succès.") if isinstance(data, dict) else "Colis ajouté avec succès.",
                "district_id": district_id,
                "city": city_label,
                "quick_product_id": product_id,
                "quantity": quantity,
                "shipping_cost": billed,
                "raw": data,
            }
        fail_status = res.status_code if 400 <= res.status_code < 500 else 400
        return {
            "success": False,
            "ok": False,
            "error": _error_text(data, res.text),
            "detail": _error_text(data, res.text),
            "status_code": fail_status,
            "district_id": district_id,
            "city": city_label,
            "quick_product_id": product_id,
            "quantity": quantity,
            "raw": data,
        }
    except Exception as exc:
        log.exception("Quick stock dispatch crashed city=%r", city_label)
        detail = str(exc) or unmapped_city_detail(city_label)
        if "timeout" in detail.casefold() or "timed out" in detail.casefold():
            detail = "تعذر الاتصال بـ Quick Livraison (انتهت المهلة). حاول مرة أخرى."
        return {
            "success": False,
            "ok": False,
            "error": "quick_stock_failed",
            "detail": detail,
            "message": detail,
            "status_code": 400,
            "city": city_label,
        }
