from __future__ import annotations

import re
from typing import Any

import httpx

from app.core.config import QUICK_LIVRAISON_API_KEY

QUICK_STOCK_STORE_URL = "https://clients.quicklivraison.ma/api/deliveries/store"
QUICK_STOCK_PRODUCT_KH01 = 6005
QUICK_API_KEY_FALLBACK = "6sD6fVFImLf0SyE2pzBMdOuiNqUHEJyE"

QUICK_CITIES = {
    "casablanca": 43,
    "casa": 43,
    "الدار البيضاء": 43,
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


def _api_key() -> str:
    return (QUICK_LIVRAISON_API_KEY or QUICK_API_KEY_FALLBACK).strip() or QUICK_API_KEY_FALLBACK


def resolve_district_id(city_name: str) -> int:
    clean = (city_name or "").strip().lower()
    for key, val in QUICK_CITIES.items():
        if key in clean:
            return val
    return 43


def clean_moroccan_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("212"):
        digits = "0" + digits[3:]
    elif not digits.startswith("0") and len(digits) == 9:
        digits = "0" + digits
    return digits[-10:]


def _city_text(order: Any) -> str:
    return " ".join(
        part
        for part in (
            str(getattr(order, "shipping_city", "") or "").strip(),
            str(getattr(order, "city", "") or "").strip(),
        )
        if part
    )


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
    city = str(getattr(order, "city", "") or "").strip()
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


async def create_quick_stock_order(order: Any, product_id: int, quantity: int = 1) -> dict[str, Any]:
    """Create a Quick Livraison parcel from warehouse stock for the given Quick product ID."""
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

    district_id = resolve_district_id(_city_text(order))
    phone = _phone(order)
    payload = {
        "api_key": _api_key(),
        "district_id": district_id,
        "name": _customer_name(order),
        "amount": _cod_amount(order),
        "phone": phone,
        "address": _address(order),
        "code": f"CFG-{str(getattr(order, 'id', ''))[:8]}",
        "note": str(getattr(order, "courier_notes", "") or ""),
        "open": False,
        "received_quantity": {str(product_id): int(quantity)},
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(
                QUICK_STOCK_STORE_URL,
                json=payload,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
    except httpx.HTTPError as exc:
        return {"success": False, "error": str(exc) or "quick_stock_failed", "status_code": 502}

    try:
        data = res.json()
    except Exception:
        data = {"text": res.text}

    tracking = ""
    if isinstance(data, dict):
        tracking = str(data.get("tracking_number") or "").strip()

    if res.status_code in (200, 201) and tracking:
        return {
            "success": True,
            "ok": True,
            "tracking_number": tracking,
            "message": data.get("success", "Colis ajouté avec succès.") if isinstance(data, dict) else "Colis ajouté avec succès.",
            "district_id": district_id,
            "quick_product_id": product_id,
            "quantity": quantity,
            "raw": data,
        }
    return {
        "success": False,
        "ok": False,
        "error": _error_text(data, res.text),
        "status_code": res.status_code,
        "district_id": district_id,
        "quick_product_id": product_id,
        "quantity": quantity,
        "raw": data,
    }
