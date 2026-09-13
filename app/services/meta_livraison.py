from __future__ import annotations

import json
import os
import re
import traceback
import unicodedata
from io import BytesIO
from typing import Any

import httpx
from pypdf import PdfReader, PdfWriter

from app.services.meta_livraison_cities import (
    FALLBACK_VILLE,
    fold_city,
    has_arabic,
    is_official_meta_city,
    latin_ville,
    resolve_meta_city,
)

EMPTY_KEYS = {"", "YOUR_API_KEY_HERE", "YOUR_API_SECRET_HERE"}
DEFAULT_BASE = "https://api.metalivraison.ma/colis-service"
COLIS_PATH = "/api/v1/partner/colis"
PACK_NAMES = {
    "quran": "USB القرآن",
    "taalim": "USB التعليمي",
    "music": "USB الموسيقى",
    "zit_alfasokh": "زيت الفسوخ",
    "alkhatm_alrijali": "الخاتم الرجالي",
    "almisk_alabyad": "المسك الأبيض",
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


def latin_city(raw: str) -> str:
    return latin_ville(raw)


def _official_ville(*candidates: str) -> str:
    """Return Meta's exact official city string. Never strip hubs or dashes."""
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        if is_official_meta_city(text) and not has_arabic(text):
            return text
        resolved = resolve_meta_city(text)
        if resolved and is_official_meta_city(resolved) and not has_arabic(resolved):
            return resolved
    return FALLBACK_VILLE


def sanitize_meta_address(address: str) -> str:
    text = re.sub(r"\s+", " ", (address or "").replace("\u202c", "")).strip(" -")
    return text or "Centre Ville"


def _append_locality(address: str, locality: str, ville: str) -> str:
    loc = (locality or "").strip()
    addr = (address or "").strip()
    if not loc or loc == ville or loc in addr:
        return addr or ville or "Centre Ville"
    if not addr or addr == ville:
        return f"{ville} - {loc}" if ville else loc
    return f"{addr} - {loc}"


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
    shipping_city = _text(
        getattr(order, "shipping_city", None),
        getattr(order, "meta_city", None),
        fallback="",
    )
    ville = _official_ville(shipping_city, raw_city)
    unmapped = ville == FALLBACK_VILLE and not (
        is_official_meta_city(shipping_city) or is_official_meta_city(raw_city)
    )
    print(
        f"[META_LIVRAISON_CITY] raw={raw_city!r} shipping={shipping_city!r} "
        f"official={ville!r} sent={ville!r} unmapped={unmapped}",
        flush=True,
    )
    raw_address = _text(getattr(order, "address", None), fallback="")
    if not raw_address or raw_address == raw_city:
        address = ville or "Centre Ville"
    else:
        address = raw_address
    if raw_city and fold_city(raw_city) != fold_city(ville):
        address = _append_locality(address, raw_city, ville)
    address = sanitize_meta_address(address)
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
    try:
        if isinstance(value, dict):
            for key in ("url", "href", "link", "etiquette", "pdf", "ticket_url"):
                found = _as_ticket_url(value.get(key), base)
                if found:
                    return found
            return ""
        text = str(value or "").strip()
        if not text or text.lower() in {"true", "false", "none", "null"}:
            return ""
        root = str(base or "").rstrip("/")
        if text.startswith("/"):
            return f"{root}{text}" if root else text
        if text.startswith("http://") or text.startswith("https://"):
            return text
        return ""
    except Exception:
        return ""


def _etiquette_fallback(base: str, code: str) -> str:
    root = str(base or "").rstrip("/")
    colis_code = str(code or "").strip()
    if not root or not colis_code:
        return ""
    if root.endswith(COLIS_PATH):
        return f"{root}/{colis_code}/etiquette"
    return f"{root}{COLIS_PATH}/{colis_code}/etiquette"


def _pick_ticket_url(payload: Any, base: str = "", code: str = "") -> str:
    try:
        root = str(base or "").rstrip("/")
        for layer in _payload_layers(payload):
            for key in (
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
            ):
                found = _as_ticket_url(layer.get(key), root)
                if found:
                    return found
        return _etiquette_fallback(root, code)
    except Exception:
        traceback.print_exc()
        try:
            return _etiquette_fallback(base, code)
        except Exception:
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
        tracking = code
        ticket = ""
        try:
            parsed = detail if isinstance(detail, dict) else {}
            tracking = _pick_code(parsed, code) or code
            ticket = _pick_ticket_url(parsed, raw_base, tracking) or _etiquette_fallback(raw_base, tracking)
        except Exception:
            traceback.print_exc()
            print("[META_LIVRAISON_PARSE_ERROR] Meta already created the parcel; keeping success", flush=True)
            try:
                ticket = _etiquette_fallback(raw_base, tracking or code)
            except Exception:
                ticket = ""
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


def etiquette_url_for(code: str, ticket_url: str = "", base: str | None = None) -> str:
    ticket = str(ticket_url or "").strip()
    if ticket.startswith("http://") or ticket.startswith("https://"):
        return ticket
    return _etiquette_fallback(base_url(base), code)


def fetch_etiquette_pdf(
    *,
    code: str = "",
    ticket_url: str = "",
    api_key: str | None = None,
    api_secret: str | None = None,
    base_url_override: str | None = None,
) -> bytes | None:
    key = _clean(api_key) or live_env("META_LIVRAISON_API_KEY")
    secret = _clean(api_secret) or live_env("META_LIVRAISON_API_SECRET")
    raw_base = _clean(base_url_override) or live_env("META_LIVRAISON_BASE_URL", DEFAULT_BASE)
    url = etiquette_url_for(code, ticket_url, raw_base)
    if not url:
        return None
    headers = {
        "Accept": "application/pdf, application/octet-stream, */*",
        "X-API-Key": key,
        "X-API-Secret": secret,
    }
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            res = client.get(url, headers=headers)
        if res.status_code >= 400:
            print(f"[META_ETIQUETTE] GET {url} -> {res.status_code}", flush=True)
            return None
        body = res.content or b""
        if body[:4] != b"%PDF":
            print(f"[META_ETIQUETTE] not a PDF ({res.headers.get('content-type')})", flush=True)
            return None
        return body
    except Exception:
        traceback.print_exc()
        return None


def merge_label_pdfs(blobs: list[bytes]) -> bytes:
    writer = PdfWriter()
    for blob in blobs:
        if not blob:
            continue
        reader = PdfReader(BytesIO(blob))
        for page in reader.pages:
            writer.add_page(page)
    if not writer.pages:
        raise ValueError("no_labels")
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _fold_status(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("-", " ").replace("_", " ").replace("/", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_meta_status(raw: str) -> str | None:
    """Map a Meta Livraison etat string to delivered | returned | cancelled | in_shipping."""
    folded = _fold_status(raw)
    if not folded:
        return None
    compact = folded.replace(" ", "_")
    if any(token in folded for token in ("retour", "return", "مرتجع")):
        return "returned"
    if any(token in folded for token in ("annul", "refus", "cancel", "ملغ")):
        return "cancelled"
    if compact in {"en_cours", "expedie", "expediee", "in_shipping"}:
        return "in_shipping"
    if any(
        token in folded
        for token in ("en cours", "expedie", "shipped", "ramass", "distribution", "قيد الشحن", "en livraison")
    ):
        return "in_shipping"
    if any(token in folded for token in ("non livre", "pas livre", "not delivered")):
        return "in_shipping"
    if compact in {"livre", "livree", "delivered", "delivre"}:
        return "delivered"
    if re.search(r"(^|[^a-z])livr[eé]e?([^a-z]|$)", folded) or any(
        token in folded for token in ("تم التوصيل", "تم التسليم")
    ):
        return "delivered"
    return None


def _status_candidates(payload: Any, depth: int = 0) -> list[str]:
    keys = (
        "statut",
        "status",
        "etat",
        "state",
        "situation",
        "lastStatus",
        "last_status",
        "statusCode",
        "status_code",
        "etatColis",
        "etat_colis",
        "lastEtat",
    )
    found: list[str] = []
    if depth > 4:
        return found
    for layer in _payload_layers(payload):
        for key in keys:
            value = layer.get(key)
            if value in (None, "", True, False):
                continue
            if isinstance(value, dict):
                for nested in ("code", "name", "libelle", "label", "etat", "status"):
                    inner = value.get(nested)
                    if inner not in (None, ""):
                        found.append(str(inner))
            else:
                found.append(str(value))
        history = layer.get("historique") or layer.get("history") or layer.get("events") or layer.get("tracking")
        if isinstance(history, list) and history:
            last = history[-1]
            if isinstance(last, dict):
                found.extend(_status_candidates(last, depth + 1))
            elif last not in (None, ""):
                found.append(str(last))
    return found


def tracking_url(tracking_code: str, override: str | None = None) -> str:
    code = str(tracking_code or "").strip()
    root = colis_url(override).rstrip("/")
    return f"{root}/{code}" if code else root


def get_order_status_from_meta(
    tracking_code: str,
    *,
    api_key: str | None = None,
    api_secret: str | None = None,
    base_url_override: str | None = None,
) -> dict[str, Any]:
    code = str(tracking_code or "").strip()
    if not code:
        return {"ok": False, "status": None, "raw": "", "error": "missing_tracking_code", "detail": None}
    key = _clean(api_key) or live_env("META_LIVRAISON_API_KEY")
    secret = _clean(api_secret) or live_env("META_LIVRAISON_API_SECRET")
    if not configured(key, secret):
        return {"ok": False, "status": None, "raw": "", "error": "meta_livraison_not_configured", "detail": None}
    url = tracking_url(code, base_url_override)
    headers = {
        "Accept": "application/json",
        "X-API-Key": key,
        "X-API-Secret": secret,
    }
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            res = client.get(url, headers=headers)
        detail = _meta_detail(res)
        if res.status_code >= 400:
            return {
                "ok": False,
                "status": None,
                "raw": res.text[:500],
                "error": f"http_{res.status_code}",
                "detail": detail,
            }
        parsed = detail if isinstance(detail, dict) else {}
        candidates = _status_candidates(parsed)
        if isinstance(detail, str):
            candidates.append(detail)
        status = None
        raw = ""
        for candidate in candidates:
            status = normalize_meta_status(candidate)
            if status:
                raw = candidate
                break
        if not status:
            blob = res.text
            status = normalize_meta_status(blob)
            raw = blob[:120]
        return {
            "ok": True,
            "status": status or "in_shipping",
            "raw": raw,
            "error": "",
            "detail": detail,
        }
    except Exception as err:
        traceback.print_exc()
        return {"ok": False, "status": None, "raw": "", "error": str(err), "detail": None}
