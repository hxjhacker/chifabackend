from __future__ import annotations

from typing import Any

import httpx

from app.config import settings

EMPTY_KEYS = {"", "YOUR_API_KEY_HERE", "YOUR_API_SECRET_HERE"}


def configured() -> bool:
    key = (settings.meta_livraison_api_key or "").strip()
    secret = (settings.meta_livraison_api_secret or "").strip()
    return bool(key and secret and key not in EMPTY_KEYS and secret not in EMPTY_KEYS)


def base_url() -> str:
    return (settings.meta_livraison_base_url or "https://api.metalivraison.ma/colis-service").strip().rstrip("/")


def _national_phone(phone: str, phone_national: str) -> str:
    digits = "".join(ch for ch in (phone_national or phone or "") if ch.isdigit())
    if len(digits) == 10:
        return digits
    if len(digits) == 12 and digits.startswith("212"):
        return f"0{digits[3:]}"
    if len(digits) == 9:
        return f"0{digits}"
    return digits


def _pick_code(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    nested = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    colis = nested.get("colis") if isinstance(nested.get("colis"), dict) else nested
    for key in ("code", "tracking", "tracking_code", "trackingCode", "num_colis", "numColis", "reference", "ref"):
        value = colis.get(key) or nested.get(key) or payload.get(key)
        if value:
            return str(value).strip()
    return ""


def create_colis(order: Any) -> dict[str, Any]:
    if not configured():
        return {"ok": False, "status": 503, "detail": "meta_livraison_not_configured", "code": ""}

    price = round(float(getattr(order, "total_cents", 0) or 0) / 100)
    phone = _national_phone(str(getattr(order, "phone", "") or ""), str(getattr(order, "phone_national", "") or ""))
    address = str(getattr(order, "address", "") or getattr(order, "city", "") or "").strip()
    pack = str(getattr(order, "product_slug", "") or "")
    body = {
        "reference": str(order.id),
        "nom": order.full_name,
        "fullname": order.full_name,
        "telephone": phone,
        "phone": phone,
        "ville": order.city,
        "city": order.city,
        "adresse": address,
        "address": address,
        "prix": price,
        "price": price,
        "crbt": price,
        "produit": pack,
        "product": pack,
        "commentaire": getattr(order, "courier_notes", None) or "",
        "note": getattr(order, "courier_notes", None) or "",
        "ouverture": 1,
        "openpackage": 1,
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-API-KEY": settings.meta_livraison_api_key.strip(),
        "X-API-SECRET": settings.meta_livraison_api_secret.strip(),
        "Api-Key": settings.meta_livraison_api_key.strip(),
        "Api-Secret": settings.meta_livraison_api_secret.strip(),
    }
    try:
        with httpx.Client(timeout=25.0) as client:
            res = client.post(base_url(), json=body, headers=headers)
        payload = res.json() if res.content else {}
        code = _pick_code(payload)
        if res.status_code >= 400:
            detail = ""
            if isinstance(payload, dict):
                detail = str(payload.get("message") or payload.get("detail") or payload.get("error") or "")
            return {"ok": False, "status": res.status_code, "detail": detail or "meta_livraison_failed", "code": code}
        return {"ok": True, "status": res.status_code, "detail": "", "code": code}
    except Exception as err:
        print("meta_livraison_failed", err)
        return {"ok": False, "status": 502, "detail": "meta_livraison_failed", "code": ""}
