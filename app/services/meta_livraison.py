from __future__ import annotations

import json
import os
import traceback
from typing import Any

import httpx

EMPTY_KEYS = {"", "YOUR_API_KEY_HERE", "YOUR_API_SECRET_HERE"}
DEFAULT_BASE = "https://api.metalivraison.ma/colis-service"
COLIS_PATH = "/api/v1/partner/colis"
PACK_NAMES = {
    "quran": "مصحف شيفا جلو",
    "educative": "حصيرة تعليمية",
}
ARABIC_CITY_MAP = {
    "الرباط": "Rabat",
    "الدار البيضاء": "Casablanca",
    "كازا": "Casablanca",
    "مراكش": "Marrakech",
    "طنجة": "Tanger",
    "فاس": "Fes",
    "مكناس": "Meknes",
    "سلا": "Sale",
    "أكادير": "Agadir",
    "القنيطرة": "Kenitra",
    "وجدة": "Oujda",
    "تطوان": "Tetouan",
    "تمارة": "Temara",
    "المحمدية": "Mohammedia",
    "الجديدة": "El Jadida",
    "بني ملال": "Beni Mellal",
    "الناظور": "Nador",
    "خريبكة": "Khouribga",
    "سطات": "Settat",
    "برشيد": "Berrechid",
    "العرائش": "Larache",
    "الخميسات": "Khemisset",
    "كلميم": "Guelmim",
    "بركان": "Berkane",
    "التازة": "Taza",
    "تازة": "Taza",
}


def _clean(value: str | None) -> str:
    text = (value or "").strip().lstrip("\ufeff")
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    return text


def live_env(name: str, fallback: str = "") -> str:
    """Read process env at call time. Never uses pydantic Settings."""
    direct = os.getenv(name)
    if direct is None:
        direct = os.environ.get(name)
    if not direct:
        wanted = name.casefold()
        for key, value in os.environ.items():
            if key.casefold() == wanted:
                direct = value
                break
    return _clean(direct if direct is not None else fallback)


def api_key() -> str:
    return live_env("META_LIVRAISON_API_KEY")


def api_secret() -> str:
    return live_env("META_LIVRAISON_API_SECRET")


def base_url(override: str | None = None) -> str:
    raw = _clean(override) or live_env("META_LIVRAISON_BASE_URL", DEFAULT_BASE)
    return raw.rstrip("/")


def configured(key: str | None = None, secret: str | None = None) -> bool:
    key = _clean(key) or api_key()
    secret = _clean(secret) or api_secret()
    return bool(key and secret and key not in EMPTY_KEYS and secret not in EMPTY_KEYS)


def colis_url(override: str | None = None) -> str:
    base = base_url(override)
    if base.endswith(COLIS_PATH):
        return base
    return f"{base}{COLIS_PATH}"


def debug_credentials(key: str = "", secret: str = "", base: str = "") -> None:
    key = _clean(key) or api_key()
    secret = _clean(secret) or api_secret()
    raw_base = base or live_env("META_LIVRAISON_BASE_URL", DEFAULT_BASE)
    names = sorted(k for k in os.environ if "LIVRAISON" in k.upper() or k.startswith("META_"))
    print(f"[DEBUG META LIVRAISON] Base URL: {raw_base.rstrip('/')}")
    print(f"[DEBUG META LIVRAISON] Key length: {len(key)}, Key prefix: {key[:6]}...")
    print(f"[DEBUG META LIVRAISON] Secret length: {len(secret)}, Secret prefix: {secret[:6]}...")
    print(f"[DEBUG META LIVRAISON] POST URL: {colis_url(raw_base)}")
    print(f"[DEBUG META LIVRAISON] os.environ names: {names}")
    print(f"[DEBUG META LIVRAISON] getenv is None: key={os.getenv('META_LIVRAISON_API_KEY') is None} secret={os.getenv('META_LIVRAISON_API_SECRET') is None}")
    print(f"[DEBUG META LIVRAISON] in os.environ: key={'META_LIVRAISON_API_KEY' in os.environ} secret={'META_LIVRAISON_API_SECRET' in os.environ}")


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
    return f"ORD-{order_id}"


def _text(*values: Any, fallback: str = "") -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return fallback


def _city_lookup() -> dict[str, str]:
    table: dict[str, str] = {}
    for arabic, french in ARABIC_CITY_MAP.items():
        table[" ".join(arabic.split())] = french
        table[" ".join(french.split()).casefold()] = french
    return table


_CITY_LOOKUP = _city_lookup()


def latin_city(raw: str) -> str:
    text = " ".join((raw or "").strip().split())
    if not text:
        return ""
    mapped = _CITY_LOOKUP.get(text) or _CITY_LOOKUP.get(text.casefold())
    if mapped:
        return mapped
    try:
        from app.services.cities import find_city

        found = find_city(text)
        french = str((found or {}).get("fr") or "").strip()
        if french:
            return _CITY_LOOKUP.get(french) or _CITY_LOOKUP.get(french.casefold()) or french
    except Exception:
        pass
    return text


def build_payload(order: Any, phone: str) -> dict[str, Any]:
    destinataire = _text(
        getattr(order, "full_name", None),
        getattr(order, "customer_name", None),
        getattr(order, "name", None),
        fallback="Client",
    )
    raw_price = float(getattr(order, "total_cents", 0) or 0) / 100
    price: int | float = int(raw_price) if raw_price.is_integer() else round(raw_price, 2)
    raw_city = _text(getattr(order, "city", None), fallback="")
    ville = latin_city(raw_city)
    raw_address = _text(getattr(order, "address", None), fallback="")
    if not raw_address or raw_address == raw_city:
        address = ville or "Centre Ville"
    else:
        address = latin_city(raw_address) if raw_address in ARABIC_CITY_MAP else raw_address
    slug = _text(getattr(order, "product_slug", None))
    marchendise = _text(PACK_NAMES.get(slug, slug), fallback="Produit")
    quantity = int(getattr(order, "tier_qty", None) or getattr(order, "quantity", None) or 1)
    if quantity < 1:
        quantity = 1
    code = parcel_code(str(getattr(order, "id", "") or "ORDER"))
    return {
        "destinataire": destinataire,
        "colisStock": False,
        "canOpen": True,
        "replaceColis": False,
        "phone": phone,
        "ville": ville,
        "city": ville,
        "address": address,
        "adresse": address,
        "price": price,
        "code": code,
        "marchendise": marchendise,
        "quantity": quantity,
    }


def _payload_layers(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    layers: list[dict[str, Any]] = [payload]
    for key in ("data", "colis", "result", "parcel", "package"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            layers.append(nested)
            inner = nested.get("colis")
            if isinstance(inner, dict):
                layers.append(inner)
    return layers


def _pick_code(payload: Any, fallback: str = "") -> str:
    keys = (
        "code",
        "tracking_number",
        "trackingNumber",
        "tracking",
        "tracking_code",
        "trackingCode",
        "num_colis",
        "numColis",
        "reference",
        "ref",
    )
    for layer in _payload_layers(payload):
        for key in keys:
            value = layer.get(key)
            if value not in (None, ""):
                text = str(value).strip()
                if text:
                    return text
    return fallback


def _as_ticket_url(value: Any, base: str = "") -> str:
    if isinstance(value, dict):
        for key in ("url", "href", "link", "etiquette", "pdf", "ticket_url"):
            found = _as_ticket_url(value.get(key), base)
            if found:
                return found
        return ""
    text = str(value or "").strip()
    if not text or text.lower() in {"true", "false", "none", "null"}:
        return ""
    if text.startswith("/"):
        root = base.rstrip("/")
        return f"{root}{text}" if root else text
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return ""


def _pick_ticket_url(payload: Any, base: str = "") -> str:
    keys = (
        "etiquette",
        "etiquette_url",
        "url_etiquette",
        "lien_etiquette",
        "ticket_url",
        "ticketUrl",
        "label_url",
        "labelUrl",
        "pdf_url",
        "pdfUrl",
        "pdf",
        "ticket",
        "label",
    )
    for layer in _payload_layers(payload):
        for key in keys:
            found = _as_ticket_url(layer.get(key), base)
            if found:
                return found
    return ""


def _meta_detail(res: httpx.Response) -> Any:
    content_type = (res.headers.get("content-type") or "").lower()
    if content_type.startswith("application/json"):
        try:
            return res.json()
        except Exception:
            return res.text
    return res.text


def create_colis(
    order: Any,
    *,
    api_key: str | None = None,
    api_secret: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    key = _clean(api_key) or live_env("META_LIVRAISON_API_KEY")
    secret = _clean(api_secret) or live_env("META_LIVRAISON_API_SECRET")
    raw_base = _clean(base_url) or live_env("META_LIVRAISON_BASE_URL", DEFAULT_BASE)
    debug_credentials(key, secret, raw_base)
    if not configured(key, secret):
        return {"ok": False, "status": 400, "detail": "meta_livraison_not_configured", "code": "", "ticket_url": "", "text": ""}

    phone = _national_phone(str(getattr(order, "phone", "") or ""), str(getattr(order, "phone_national", "") or ""))
    if not (len(phone) == 10 and phone.startswith("0")):
        return {
            "ok": False,
            "status": 400,
            "detail": {"phone": "must be 10 digits starting with 0", "value": phone},
            "code": "",
            "ticket_url": "",
            "text": f"invalid phone: {phone}",
        }

    payload = build_payload(order, phone)
    code = str(payload["code"])
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-API-Key": key,
        "X-API-Secret": secret,
    }
    post_url = colis_url(raw_base)
    print("[META_LIVRAISON_REQUEST_PAYLOAD]", payload, flush=True)
    print("[META_LIVRAISON_REQUEST_JSON]", json.dumps(payload, ensure_ascii=False), flush=True)
    print(f"[DEBUG META LIVRAISON] sending POST {post_url}", flush=True)
    print(f"[DEBUG META LIVRAISON] sending header names: {list(headers.keys())}", flush=True)
    print(f"[DEBUG META LIVRAISON] sending key prefix: {key[:6]}..., len={len(key)}", flush=True)
    print(f"[DEBUG META LIVRAISON] sending secret prefix: {secret[:6]}..., len={len(secret)}", flush=True)
    try:
        with httpx.Client(timeout=15.0) as client:
            res = client.post(post_url, json=payload, headers=headers)
        print("STATUS FROM META:", res.status_code)
        print("RAW BODY FROM META:", res.text)
        detail = _meta_detail(res)
        if res.status_code >= 400:
            return {
                "ok": False,
                "status": res.status_code,
                "detail": detail,
                "code": code,
                "ticket_url": "",
                "text": res.text,
            }
        parsed = detail if isinstance(detail, dict) else {}
        tracking = _pick_code(parsed, code)
        ticket = _pick_ticket_url(parsed, base_url(raw_base))
        print("[META_LIVRAISON_TRACKING]", tracking, flush=True)
        print("[META_LIVRAISON_TICKET_URL]", ticket, flush=True)
        return {
            "ok": True,
            "status": res.status_code,
            "detail": detail,
            "code": tracking,
            "ticket_url": ticket,
            "text": res.text,
        }
    except Exception as err:
        traceback.print_exc()
        return {"ok": False, "status": 500, "detail": str(err), "code": "", "ticket_url": "", "text": str(err)}
