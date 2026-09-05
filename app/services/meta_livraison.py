from __future__ import annotations

import os
import traceback
from typing import Any

import httpx

EMPTY_KEYS = {"", "YOUR_API_KEY_HERE", "YOUR_API_SECRET_HERE"}
DEFAULT_BASE = "https://api.metalivraison.ma/colis-service"


def _env(name: str, fallback: str = "") -> str:
    return (os.getenv(name) or fallback).strip()


def configured() -> bool:
    key = _env("META_LIVRAISON_API_KEY")
    secret = _env("META_LIVRAISON_API_SECRET")
    return bool(key and secret and key not in EMPTY_KEYS and secret not in EMPTY_KEYS)


def base_url() -> str:
    return _env("META_LIVRAISON_BASE_URL", DEFAULT_BASE).rstrip("/")


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
    key = _env("META_LIVRAISON_API_KEY")
    secret = _env("META_LIVRAISON_API_SECRET")
    if not configured():
        return {"ok": False, "status": 400, "detail": "meta_livraison_not_configured", "code": "", "text": ""}

    price = round(float(getattr(order, "total_cents", 0) or 0) / 100)
    phone = _national_phone(str(getattr(order, "phone", "") or ""), str(getattr(order, "phone_national", "") or ""))
    address = str(getattr(order, "address", "") or getattr(order, "city", "") or "").strip()
    pack = str(getattr(order, "product_slug", "") or "")
    body = {
        "reference": str(getattr(order, "id", "")),
        "nom": getattr(order, "full_name", "") or "",
        "fullname": getattr(order, "full_name", "") or "",
        "telephone": phone,
        "phone": phone,
        "ville": getattr(order, "city", "") or "",
        "city": getattr(order, "city", "") or "",
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
        "X-API-Key": key,
        "X-API-Secret": secret,
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            res = client.post(base_url(), json=body, headers=headers)
        text = res.text or ""
        payload: Any = {}
        try:
            payload = res.json() if text else {}
        except Exception:
            payload = {}
        if res.status_code >= 400:
            print(
                "401 details:" if res.status_code == 401 else "meta_livraison_http_error:",
                {"origin": "meta_livraison", "status": res.status_code, "error": text[:2000]},
            )
            return {
                "ok": False,
                "status": res.status_code,
                "detail": text or "meta_livraison_failed",
                "code": _pick_code(payload),
                "text": text,
            }
        return {"ok": True, "status": res.status_code, "detail": "", "code": _pick_code(payload), "text": text}
    except Exception as err:
        traceback.print_exc()
        return {"ok": False, "status": 500, "detail": str(err), "code": "", "text": str(err)}
