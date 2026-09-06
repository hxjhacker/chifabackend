from __future__ import annotations

import time
import traceback
from typing import Any

import httpx

from app.config import settings

EMPTY_KEYS = {"", "YOUR_API_KEY_HERE", "YOUR_API_SECRET_HERE"}
DEFAULT_BASE = "https://api.metalivraison.ma"
COLIS_PATH = "/api/v1/partner/colis"
PACK_NAMES = {
    "quran": "مصحف شيفا جلو",
    "educative": "حصيرة تعليمية",
}


def _env(value: str | None, fallback: str = "") -> str:
    return (value or fallback).strip()


def configured() -> bool:
    key = _env(settings.meta_livraison_api_key)
    secret = _env(settings.meta_livraison_api_secret)
    return bool(key and secret and key not in EMPTY_KEYS and secret not in EMPTY_KEYS)


def colis_url() -> str:
    base = _env(settings.meta_livraison_base_url, DEFAULT_BASE).rstrip("/")
    if base.endswith(COLIS_PATH):
        return base
    if base.endswith("/colis-service"):
        base = base[: -len("/colis-service")]
    return f"{base}{COLIS_PATH}"


def _national_phone(phone: str, phone_national: str) -> str:
    digits = "".join(ch for ch in (phone_national or phone or "") if ch.isdigit())
    if digits.startswith("212") and len(digits) >= 12:
        digits = "0" + digits[3:]
    elif len(digits) == 9 and digits[0] in "567":
        digits = "0" + digits
    if len(digits) == 10 and digits.startswith("0"):
        return digits
    return digits


def parcel_code(order_id: str) -> str:
    return f"ORD-{str(order_id)[:8]}-{int(time.time())}"


def _pick_code(payload: Any, fallback: str = "") -> str:
    if not isinstance(payload, dict):
        return fallback
    nested = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    colis = nested.get("colis") if isinstance(nested.get("colis"), dict) else nested
    for key in ("code", "tracking", "tracking_code", "trackingCode", "num_colis", "numColis", "reference", "ref"):
        value = colis.get(key) or nested.get(key) or payload.get(key)
        if value:
            return str(value).strip()
    return fallback


def _meta_detail(res: httpx.Response) -> Any:
    content_type = (res.headers.get("content-type") or "").lower()
    if content_type.startswith("application/json"):
        try:
            return res.json()
        except Exception:
            return res.text
    return res.text


def create_colis(order: Any) -> dict[str, Any]:
    key = _env(settings.meta_livraison_api_key)
    secret = _env(settings.meta_livraison_api_secret)
    if not configured():
        return {"ok": False, "status": 400, "detail": "meta_livraison_not_configured", "code": "", "text": ""}

    phone = _national_phone(str(getattr(order, "phone", "") or ""), str(getattr(order, "phone_national", "") or ""))
    if not (len(phone) == 10 and phone.startswith("0")):
        return {
            "ok": False,
            "status": 400,
            "detail": {"phone": "must be 10 digits starting with 0", "value": phone},
            "code": "",
            "text": f"invalid phone: {phone}",
        }

    raw_price = float(getattr(order, "total_cents", 0) or 0) / 100
    price: int | float = int(raw_price) if raw_price.is_integer() else round(raw_price, 2)
    ville = str(getattr(order, "city", "") or "").strip()
    address = str(getattr(order, "address", "") or ville).strip()
    slug = str(getattr(order, "product_slug", "") or "").strip()
    pack = PACK_NAMES.get(slug, slug)
    qty = int(getattr(order, "tier_qty", 1) or 1)
    if qty > 1:
        pack = f"{pack} × {qty}"
    code = parcel_code(str(getattr(order, "id", "")))
    body = {
        "code": code,
        "reference": code,
        "nom": str(getattr(order, "full_name", "") or "").strip(),
        "fullname": str(getattr(order, "full_name", "") or "").strip(),
        "telephone": phone,
        "phone": phone,
        "ville": ville,
        "city": ville,
        "adresse": address,
        "address": address,
        "prix": price,
        "price": price,
        "crbt": price,
        "produit": pack,
        "product": pack,
        "commentaire": str(getattr(order, "courier_notes", None) or "").strip(),
        "note": str(getattr(order, "courier_notes", None) or "").strip(),
        "ouverture": 1,
        "openpackage": 1,
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-API-Key": key,
        "X-API-Secret": secret,
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            res = client.post(colis_url(), json=body, headers=headers)
        print("STATUS FROM META:", res.status_code)
        print("RAW BODY FROM META:", res.text)
        detail = _meta_detail(res)
        if res.status_code >= 400:
            return {
                "ok": False,
                "status": res.status_code,
                "detail": detail,
                "code": code,
                "text": res.text,
            }
        return {
            "ok": True,
            "status": res.status_code,
            "detail": detail,
            "code": _pick_code(detail if isinstance(detail, dict) else {}, code),
            "text": res.text,
        }
    except Exception as err:
        traceback.print_exc()
        return {"ok": False, "status": 500, "detail": str(err), "code": "", "text": str(err)}
