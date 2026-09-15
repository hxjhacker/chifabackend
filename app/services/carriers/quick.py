from __future__ import annotations

import asyncio
import logging
import time
import unicodedata
from typing import Any, Sequence
from urllib.parse import quote

import httpx
from sqlmodel import Session, select

from app.core.config import QUICK_LIVRAISON_API_KEY, QUICK_LIVRAISON_API_URL
from app.db import engine
from app.models import CityTarif
from app.services.carriers.base import ShippingCarrierBase
from app.services.city_tarifs import city_match_keys, fold_city
from app.services.meta_livraison_cities import resolve_meta_city
from app.utils.regions import is_region_label

log = logging.getLogger(__name__)

EMPTY_KEYS = {"", "YOUR_API_KEY_HERE"}
HUB_CITY_FOLDS = ("fes", "fez", "fas", "fès")
QUICK_HTTP_TIMEOUT = 10.0
_CITY_CACHE_TTL_SECONDS = 60 * 60
_city_mapping_cache: dict[str, int] | None = None
_city_mapping_cached_at = 0.0
_city_mapping_lock: asyncio.Lock | None = None


def _api_key() -> str:
    return (QUICK_LIVRAISON_API_KEY or "").strip()


def _city_cache_lock() -> asyncio.Lock:
    global _city_mapping_lock
    if _city_mapping_lock is None:
        _city_mapping_lock = asyncio.Lock()
    return _city_mapping_lock


def _cached_city_mapping_if_fresh() -> dict[str, int] | None:
    if not _city_mapping_cache:
        return None
    if (time.monotonic() - _city_mapping_cached_at) >= _CITY_CACHE_TTL_SECONDS:
        return None
    return _city_mapping_cache


def _store_city_mapping(mapping: dict[str, int]) -> None:
    global _city_mapping_cache, _city_mapping_cached_at
    if not mapping:
        return
    _city_mapping_cache = mapping
    _city_mapping_cached_at = time.monotonic()
    log.info("Cached %s Quick city ids", len(mapping))


async def cached_city_mapping(*, force: bool = False) -> dict[str, int]:
    """In-memory Quick getCityIDs map. Avoids a network round-trip on every dispatch."""
    if not force:
        fresh = _cached_city_mapping_if_fresh()
        if fresh is not None:
            return fresh
    async with _city_cache_lock():
        if not force:
            fresh = _cached_city_mapping_if_fresh()
            if fresh is not None:
                return fresh
        payload = await QuickLivraisonCarrier()._get("/getCityIDs")
        mapping = _mapping_from_city_rows(_city_rows(payload))
        if mapping:
            _store_city_mapping(mapping)
            return mapping
        if _city_mapping_cache:
            log.warning("Quick getCityIDs returned no cities; using stale cache of %s ids", len(_city_mapping_cache))
            return _city_mapping_cache
        return {}


def _base_url() -> str:
    return (QUICK_LIVRAISON_API_URL or "https://clients.quicklivraison.ma/api").rstrip("/")


PACK_NAMES = {
    "quran": "USB القرآن",
    "taalim": "USB التعليمي",
    "music": "USB الموسيقى",
    "zit_alfasokh": "زيت الفسوخ",
    "alkhatm_alrijali": "الخاتم الرجالي",
    "almisk_alabyad": "المسك الأبيض",
}


def _national_phone(phone: str, phone_national: str) -> str:
    raw = str(phone_national or phone or "").replace(" ", "").replace("-", "")
    if raw.startswith("+212"):
        raw = "0" + raw[4:]
    elif raw.startswith("212"):
        raw = "0" + raw[3:]
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits.startswith("212") and len(digits) >= 12:
        digits = "0" + digits[3:]
    elif len(digits) == 9 and digits[0] in "567":
        digits = "0" + digits
    return digits


def _order_amount(order: Any) -> float:
    """Cash-on-delivery amount in MAD. Never cents, never a string, never None."""
    if hasattr(order, "total_cents") and order.total_cents is not None:
        try:
            return round(float(order.total_cents) / 100.0, 2)
        except (TypeError, ValueError):
            pass
    if hasattr(order, "total_price") and order.total_price is not None:
        try:
            return round(float(order.total_price), 2)
        except (TypeError, ValueError):
            pass
    if hasattr(order, "price") and order.price is not None:
        try:
            return round(float(order.price), 2)
        except (TypeError, ValueError):
            pass
    total_mad = getattr(order, "total_mad", None)
    if total_mad is not None:
        try:
            return round(float(total_mad), 2)
        except (TypeError, ValueError):
            pass
    return 0.0


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _qty(order: Any) -> int:
    raw = getattr(order, "tier_qty", None) or getattr(order, "quantity", None) or 1
    try:
        qty = int(raw)
    except (TypeError, ValueError):
        return 1
    return qty if qty > 0 else 1


def _product_name(order: Any) -> str:
    slug = str(getattr(order, "product_slug", "") or "").strip()
    return PACK_NAMES.get(slug, slug) or "Article"


def _form_body(payload: dict[str, Any]) -> dict[str, str]:
    """Laravel reads montant from form-urlencoded $_POST, not from a JSON body."""
    body: dict[str, str] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, bool):
            body[key] = "true" if value else "false"
        elif isinstance(value, float):
            body[key] = f"{value:.2f}"
        else:
            body[key] = str(value)
    return body


def _parse_http_body(res: httpx.Response) -> Any:
    try:
        return res.json()
    except Exception:
        return {"text": res.text}


def _store_succeeded(status_code: int, parsed: Any) -> bool:
    if status_code not in (200, 201):
        return False
    if isinstance(parsed, dict) and parsed.get("success") is False:
        return False
    if _tracking_from(parsed):
        return True
    if not isinstance(parsed, dict):
        return False
    success = parsed.get("success")
    if success is True:
        return True
    if isinstance(success, str) and "succ" in success.casefold():
        return True
    return False


def _error_detail(parsed: Any, text: str) -> str:
    if isinstance(parsed, dict):
        for key in ("message", "error", "detail", "msg"):
            value = parsed.get(key)
            if value not in (None, "", False, True):
                return str(value)
        errors = parsed.get("errors")
        if isinstance(errors, dict):
            parts = []
            for field, msgs in errors.items():
                if isinstance(msgs, list):
                    parts.append(f"{field}: {', '.join(str(m) for m in msgs)}")
                elif msgs not in (None, ""):
                    parts.append(f"{field}: {msgs}")
            if parts:
                return "; ".join(parts)
    return text or "quick_livraison_failed"


def _city_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "cities", "result", "results", "items", "districts"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            nested = _city_rows(value)
            if nested:
                return nested
    return []


def _district_id(row: dict[str, Any]) -> int | None:
    for key in ("district_id", "districtId", "city_id", "cityId", "id"):
        found = _as_int(row.get(key))
        if found is not None:
            return found
    return None


def _city_name(row: dict[str, Any]) -> str:
    for key in ("city_name", "cityName", "name", "ville", "city", "label", "district_name"):
        text = str(row.get(key) or "").strip()
        if text:
            return text
    return ""


def _city_display_variants(raw: str) -> list[str]:
    text = str(raw or "").strip()
    if not text or is_region_label(text):
        return []
    variants = [text, resolve_meta_city(text)]
    folded = fold_city(text)
    compact = folded.replace(" ", "")
    for key in city_match_keys(text):
        if key in {folded, compact}:
            continue
        variants.append(key)
    return variants


def _candidate_city_names(order: Any) -> list[str]:
    """Official Meta city first (`shipping_city`), then typed `city`. Never the region."""
    seen: set[str] = set()
    names: list[str] = []
    for attr in ("shipping_city", "city"):
        raw = str(getattr(order, attr, "") or "").strip()
        if not raw or is_region_label(raw):
            continue
        for name in _city_display_variants(raw):
            text = str(name or "").strip()
            key = fold_city(text)
            if not text or is_region_label(text) or not key or key in seen:
                continue
            seen.add(key)
            names.append(text)
    return names


def _district_from_mapping(mapping: dict[str, int], names: list[str]) -> int | None:
    for name in names:
        for key in city_match_keys(name):
            found = mapping.get(key)
            if found:
                return found
    return None


def _hub_district(mapping: dict[str, int]) -> int | None:
    for key in HUB_CITY_FOLDS:
        found = mapping.get(key) or mapping.get(key.replace(" ", ""))
        if found:
            return found
    return None


def _mapping_from_tarif_rows(rows: list[Any]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for row in rows:
        district_id = _as_int(getattr(row, "quick_district_id", None))
        name = str(getattr(row, "city_name", "") or "").strip()
        if not district_id or not name:
            continue
        key = fold_city(name)
        mapping[key] = district_id
        mapping[key.replace(" ", "")] = district_id
    return mapping


def _mapping_from_city_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for row in rows:
        district_id = _district_id(row)
        name = _city_name(row)
        if not district_id or not name:
            continue
        key = fold_city(name)
        mapping[key] = district_id
        mapping[key.replace(" ", "")] = district_id
    return mapping


def _product_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "products", "result", "results", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            nested = _product_rows(value)
            if nested:
                return nested
    return []


def _product_id(row: dict[str, Any]) -> int | None:
    for key in ("product_id", "productId", "prd_id", "prdId", "id"):
        found = _as_int(row.get(key))
        if found is not None:
            return found
    return None


def _product_sku(row: dict[str, Any]) -> str:
    for key in ("sku", "code", "product_code", "productCode", "ref", "reference", "prd_code"):
        text = str(row.get(key) or "").strip()
        if text:
            return text
    return ""


def _product_label(row: dict[str, Any]) -> str:
    for key in ("name", "prd_name", "label", "title", "product_name"):
        text = str(row.get(key) or "").strip()
        if text:
            return text
    return ""


def _tracking_from(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in (
            "tracking_number",
            "trackingNumber",
            "tracking",
            "code_envoi",
            "codeEnvoi",
            "code",
            "parcel_code",
            "parcelCode",
            "reference",
            "id",
        ):
            value = payload.get(key)
            if value not in (None, "", True, False):
                if isinstance(value, dict):
                    nested = _tracking_from(value)
                    if nested:
                        return nested
                    continue
                return str(value).strip()
        for key in ("data", "parcel", "delivery", "result"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                found = _tracking_from(nested)
                if found:
                    return found
    return ""


def _status_from(payload: Any) -> str:
    if not isinstance(payload, dict):
        return str(payload or "")
    for key in ("status", "etat", "state", "statut", "parcel_status", "last_status", "message", "error"):
        value = payload.get(key)
        if value not in (None, "", False, True):
            if isinstance(value, dict):
                return str(value.get("name") or value.get("label") or value.get("code") or "")
            return str(value)
    nested = payload.get("data") or payload.get("parcel") or payload.get("delivery")
    if isinstance(nested, dict):
        return _status_from(nested)
    return ""


def _payload_blob(payload: Any) -> str:
    if isinstance(payload, dict):
        parts = [str(payload.get(key) or "") for key in ("message", "error", "status", "success", "text", "detail")]
        nested = payload.get("data")
        if nested not in (None, ""):
            parts.append(str(nested))
        return " ".join(parts).casefold()
    return str(payload or "").casefold()


def _parcel_missing(payload: Any) -> bool:
    blob = _payload_blob(payload)
    return any(
        token in blob
        for token in (
            "colis non existant",
            "non existant",
            "does not exist",
            "not found",
            "not exist",
            "inconnu",
            "introuvable",
        )
    )


def tracking_lookup_codes(tracking_number: str, extra_codes: Sequence[str] | None = None) -> list[str]:
    """Quick barcode is numeric. Stored values like PARCEL_89947944 must be stripped."""
    raw = str(tracking_number or "").strip()
    codes: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        text = str(value or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        codes.append(text)

    add(raw)
    upper = raw.upper()
    if upper.startswith("PARCEL_"):
        add(raw.split("_", 1)[-1].strip())
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits:
        add(digits)
    for item in extra_codes or ():
        add(item)
    return codes


def normalize_quick_status(raw: str) -> str | None:
    folded = unicodedata.normalize("NFKD", raw or "")
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.casefold().replace("-", " ").replace("_", " ")
    if not folded:
        return None
    if _parcel_missing(raw):
        return None
    if any(token in folded for token in ("retour", "return", "مرتجع")):
        return "returned"
    if any(token in folded for token in ("annul", "cancel", "refus", "ملغ")):
        return "cancelled"
    if any(
        token in folded
        for token in ("livre", "delivered", "paye", "paid", "تم التسليم", "تم التوصيل")
    ):
        return "delivered"
    if any(token in folded for token in ("ship", "cours", "ramass", "transit", "expedi", "قيد الشحن", "distribution")):
        return "in_shipping"
    return None


class QuickLivraisonCarrier(ShippingCarrierBase):
    carrier_id = "quick_livraison"
    carrier_name = "Quick Livraison"

    def is_configured(self) -> bool:
        key = _api_key()
        return bool(key and key not in EMPTY_KEYS)

    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Content-Type": "application/json"}

    def _params(self) -> dict[str, str]:
        return {"api_key": _api_key()}

    async def _get(self, path: str) -> Any:
        url = f"{_base_url()}{path}"
        async with httpx.AsyncClient(timeout=QUICK_HTTP_TIMEOUT, follow_redirects=True) as client:
            res = await client.get(url, params=self._params(), headers=self._headers())
        try:
            return res.json()
        except Exception:
            return {"ok": False, "status": res.status_code, "text": res.text}

    async def _post(self, path: str, payload: dict[str, Any]) -> tuple[int, Any, str]:
        url = f"{_base_url()}{path}"
        body = {**payload, "api_key": _api_key()}
        async with httpx.AsyncClient(timeout=QUICK_HTTP_TIMEOUT, follow_redirects=True) as client:
            res = await client.post(url, params=self._params(), json=body, headers=self._headers())
        parsed = _parse_http_body(res)
        return res.status_code, parsed, res.text

    async def _post_store(self, payload: dict[str, Any]) -> tuple[int, Any, str]:
        """Create a parcel: form-urlencoded first (Quick cURL), then JSON if montant is still rejected."""
        url = f"{_base_url()}/deliveries/store"
        body = {**payload, "api_key": _api_key()}
        accept = {"Accept": "application/json"}
        async with httpx.AsyncClient(timeout=QUICK_HTTP_TIMEOUT, follow_redirects=True) as client:
            res = await client.post(
                url,
                params=self._params(),
                data=_form_body(body),
                headers=accept,
            )
            if res.status_code in (400, 422) and "montant" in (res.text or "").casefold():
                res = await client.post(
                    url,
                    params=self._params(),
                    json=body,
                    headers={**accept, "Content-Type": "application/json"},
                )
        return res.status_code, _parse_http_body(res), res.text

    def _district_from_db(self, order: Any, *, allow_hub: bool = True) -> int | None:
        names = _candidate_city_names(order)
        with Session(engine) as session:
            mapping = _mapping_from_tarif_rows(list(session.exec(select(CityTarif)).all()))
        found = _district_from_mapping(mapping, names)
        if found:
            return found
        return _hub_district(mapping) if allow_hub else None

    async def resolve_district_id(self, order: Any) -> int | None:
        stored = self._district_from_db(order)
        if stored:
            return stored
        mapping = await cached_city_mapping()
        names = _candidate_city_names(order)
        return _district_from_mapping(mapping, names) or _hub_district(mapping)

    def mapped_district_id(self, order: Any, session: Session | None = None) -> int | None:
        """City district_id from Quick getCityIDs mapping. No hub-city fallback."""
        names = _candidate_city_names(order)
        if session is not None:
            mapping = _mapping_from_tarif_rows(list(session.exec(select(CityTarif)).all()))
            found = _district_from_mapping(mapping, names)
            if found:
                return found
        return self._district_from_db(order, allow_hub=False)

    async def resolve_mapped_district_id(self, order: Any, session: Session | None = None) -> int | None:
        names = _candidate_city_names(order)
        mapping = await cached_city_mapping()
        return _district_from_mapping(mapping, names)

    async def _post_store_json(self, payload: dict[str, Any]) -> tuple[int, Any, str]:
        """Official Quick stock create: JSON body to POST /deliveries/store."""
        url = f"{_base_url()}/deliveries/store"
        body = {**payload, "api_key": _api_key()}
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=QUICK_HTTP_TIMEOUT, follow_redirects=True) as client:
            res = await client.post(url, json=body, headers=headers)
        return res.status_code, _parse_http_body(res), res.text

    async def list_products(self) -> list[dict[str, Any]]:
        payload = await self._get("/getProductIDs")
        rows = []
        for row in _product_rows(payload):
            product_id = _product_id(row)
            sku = _product_sku(row)
            name = _product_label(row)
            if product_id or sku or name:
                rows.append({"product_id": product_id, "sku": sku, "name": name, "raw": row})
        return rows

    async def resolve_product_id(self, sku: str, name: str = "") -> int | None:
        wanted = fold_city(sku)
        wanted_name = fold_city(name)
        if not wanted and not wanted_name:
            return None
        try:
            products = await self.list_products()
        except Exception:
            return None
        for row in products:
            row_sku = fold_city(str(row.get("sku") or ""))
            row_name = fold_city(str(row.get("name") or ""))
            product_id = _as_int(row.get("product_id"))
            if not product_id:
                continue
            if wanted and row_sku and (row_sku == wanted or wanted in row_sku or row_sku in wanted):
                return product_id
            if wanted_name and row_name and row_name == wanted_name:
                return product_id
        return None

    def _parcel_payload(
        self,
        order: Any,
        district_id: int,
        *,
        from_stock: bool = False,
        product_code: str = "",
        product_id: int | None = None,
        quantity: int | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        phone = _national_phone(
            str(getattr(order, "phone", "") or ""),
            str(getattr(order, "phone_national", "") or ""),
        )
        city = str(getattr(order, "shipping_city", "") or getattr(order, "city", "") or "").strip()
        if is_region_label(city):
            city = str(getattr(order, "city", "") or "").strip()
        address = " ".join(
            part
            for part in (
                str(getattr(order, "address", "") or "").strip(),
                str(getattr(order, "quartier", "") or "").strip(),
                str(getattr(order, "street", "") or "").strip(),
                city,
            )
            if part
        ).strip() or city or "Maroc"
        name = str(getattr(order, "full_name", "") or "").strip() or "Client"
        order_amount = _order_amount(order)
        code = str(getattr(order, "code", None) or getattr(order, "id", "") or "")
        qty = quantity if quantity is not None else _qty(order)
        comment = note if note is not None else str(getattr(order, "courier_notes", "") or "").strip()
        sku = str(product_code or getattr(order, "product_code", "") or "").strip()
        payload: dict[str, Any] = {
            "district_id": int(district_id),
            "city_id": int(district_id),
            "name": name,
            "receiver_name": name,
            "client_name": name,
            "phone": phone,
            "tel": phone,
            "address": address,
            "adresse": address,
            "amount": order_amount,
            "montant": order_amount,
            "price": order_amount,
            "prix": order_amount,
            "cod_amount": order_amount,
            "code": code,
            "open": "true",
            "prd_name": _product_name(order),
            "qte_prd": qty,
            "quantity": qty,
            "comment": comment,
            "note": comment,
            "client_order_ref": code,
            "open_package": 1,
        }
        if sku:
            payload["product_code"] = sku
            payload["sku"] = sku
            payload["prd_code"] = sku
        if product_id:
            payload["product_id"] = int(product_id)
            payload["prd_id"] = int(product_id)
        if from_stock:
            payload["from_stock"] = 1
            payload["stock"] = 1
            payload["is_stock"] = 1
            payload["expedition_type"] = "stock"
            payload["type_envoi"] = "stock"
            payload["ramassage"] = 0
        return payload

    async def _store_parcel(self, order: Any, payload: dict[str, Any]) -> dict[str, Any]:
        code = str(payload.get("code") or getattr(order, "id", "") or "")
        status_code, parsed, text = await self._post_store(payload)
        tracking = _tracking_from(parsed) or (code if _store_succeeded(status_code, parsed) else "")
        if not _store_succeeded(status_code, parsed) or not tracking:
            return {
                "ok": False,
                "tracking_number": tracking,
                "ticket_url": "",
                "carrier": self.carrier_id,
                "error": _error_detail(parsed, text),
                "raw": parsed,
            }
        ticket = ""
        if isinstance(parsed, dict):
            ticket = str(parsed.get("ticket_url") or parsed.get("tracking_url") or parsed.get("url") or "").strip()
        return {
            "ok": True,
            "tracking_number": tracking,
            "code_envoi": tracking,
            "ticket_url": ticket,
            "carrier": self.carrier_id,
            "error": "",
            "raw": parsed,
        }

    async def create_shipment(self, order: Any) -> dict[str, Any]:
        if not self.is_configured():
            return {
                "ok": False,
                "tracking_number": "",
                "ticket_url": "",
                "carrier": self.carrier_id,
                "error": "quick_livraison_not_configured",
            }
        district_id = await self.resolve_mapped_district_id(order)
        if not district_id:
            return {
                "ok": False,
                "tracking_number": "",
                "ticket_url": "",
                "carrier": self.carrier_id,
                "error": "quick_district_not_mapped",
            }
        payload = self._parcel_payload(order, district_id)
        return await self._store_parcel(order, payload)

    async def create_stock_delivery(
        self,
        payload: dict[str, Any],
        *,
        session: Session | None = None,
        order: Any = None,
    ) -> dict[str, Any]:
        """POST /deliveries/store with the official JSON stock payload."""
        if not self.is_configured():
            return {
                "ok": False,
                "tracking_number": "",
                "ticket_url": "",
                "carrier": self.carrier_id,
                "error": "quick_livraison_not_configured",
                "status_code": 400,
            }
        body = dict(payload)
        district_id = _as_int(body.get("district_id"))
        if not district_id and order is not None:
            district_id = await self.resolve_mapped_district_id(order, session)
            if district_id:
                body["district_id"] = int(district_id)
        if not _as_int(body.get("district_id")):
            return {
                "ok": False,
                "tracking_number": "",
                "ticket_url": "",
                "carrier": self.carrier_id,
                "error": "quick_district_not_mapped",
                "status_code": 400,
            }
        received = body.get("received_quantity")
        if not isinstance(received, dict) or not received:
            return {
                "ok": False,
                "tracking_number": "",
                "ticket_url": "",
                "carrier": self.carrier_id,
                "error": "quick_product_id_missing",
                "status_code": 400,
            }
        body = {key: value for key, value in body.items() if value is not None}
        status_code, parsed, text = await self._post_store_json(body)
        tracking = ""
        if isinstance(parsed, dict):
            tracking = str(parsed.get("tracking_number") or "").strip()
        if not tracking:
            tracking = _tracking_from(parsed)
        if not _store_succeeded(status_code, parsed) or not tracking:
            return {
                "ok": False,
                "tracking_number": tracking,
                "ticket_url": "",
                "carrier": self.carrier_id,
                "error": _error_detail(parsed, text),
                "raw": parsed,
                "status_code": status_code if status_code >= 400 else 400,
            }
        ticket = ""
        if isinstance(parsed, dict):
            ticket = str(parsed.get("ticket_url") or parsed.get("tracking_url") or parsed.get("url") or "").strip()
        return {
            "ok": True,
            "tracking_number": tracking,
            "code_envoi": tracking,
            "ticket_url": ticket,
            "carrier": self.carrier_id,
            "error": "",
            "raw": parsed,
            "status_code": status_code,
        }

    async def create_stock_order(self, order: Any, order_data: dict[str, Any] | None = None) -> dict[str, Any]:
        data = order_data or {}
        product_id = _as_int(data.get("quick_product_id") or data.get("product_id") or data.get("prd_id"))
        if not product_id:
            return {
                "ok": False,
                "tracking_number": "",
                "ticket_url": "",
                "carrier": self.carrier_id,
                "error": "quick_product_id_missing",
                "status_code": 400,
            }
        qty = _as_int(data.get("quantity") or data.get("received_quantity")) or _qty(order)
        phone = _national_phone(
            str(getattr(order, "phone", "") or ""),
            str(getattr(order, "phone_national", "") or ""),
        )
        city = str(getattr(order, "shipping_city", "") or getattr(order, "city", "") or "").strip()
        if is_region_label(city):
            city = str(getattr(order, "city", "") or "").strip()
        address = str(data.get("address") or getattr(order, "address", "") or "").strip() or city
        note = str(data.get("note") if data.get("note") is not None else getattr(order, "courier_notes", "") or "")
        code = data.get("code")
        if code in (None, ""):
            code = getattr(order, "code", None)
        payload: dict[str, Any] = {
            "district_id": _as_int(data.get("district_id")),
            "name": str(data.get("name") or getattr(order, "full_name", "") or "").strip() or "Client",
            "phone": phone,
            "address": address,
            "amount": _order_amount(order),
            "note": note,
            "open": False,
            "received_quantity": {str(int(product_id)): qty if qty > 0 else 1},
        }
        if code not in (None, ""):
            payload["code"] = str(code)
        return await self.create_stock_delivery(payload, order=order)

    async def get_tracking_status(self, tracking_number: str, **kwargs: Any) -> dict[str, Any]:
        extra = kwargs.get("extra_codes")
        extras = extra if isinstance(extra, (list, tuple)) else ()
        codes = tracking_lookup_codes(tracking_number, extras)
        if not codes:
            return {"ok": False, "status": "", "raw": "", "error": "missing_tracking_code", "carrier": self.carrier_id}
        last_raw = ""
        last_error = "unknown_status"
        for code in codes:
            try:
                payload = await self._get(f"/getParcelDetails/{quote(code, safe='-_')}")
            except httpx.TimeoutException:
                last_error = "quick_timeout"
                last_raw = last_raw or "timeout"
                continue
            except httpx.HTTPError as exc:
                last_error = str(exc) or "quick_tracking_failed"
                continue
            if _parcel_missing(payload):
                last_raw = _status_from(payload) or "Colis non existant"
                last_error = "unknown_status"
                continue
            raw = _status_from(payload)
            status = normalize_quick_status(raw)
            if status:
                return {
                    "ok": True,
                    "status": status,
                    "raw": raw,
                    "error": "",
                    "carrier": self.carrier_id,
                    "lookup_code": code,
                }
            last_raw = raw or last_raw
            last_error = "unknown_status"
        return {
            "ok": False,
            "status": "",
            "raw": last_raw,
            "error": last_error,
            "carrier": self.carrier_id,
        }

    async def cancel_shipment(self, tracking_number: str) -> bool:
        code = str(tracking_number or "").strip()
        if not code:
            return False
        status_code, parsed, _text = await self._post("/deliveries/cancel", {"tracking_number": code, "code": code})
        if status_code >= 400:
            return False
        if isinstance(parsed, dict) and parsed.get("success") is False:
            return False
        return True

    async def list_cities(self) -> list[dict[str, Any]]:
        payload = await self._get("/getCityIDs")
        rows = []
        for row in _city_rows(payload):
            district_id = _district_id(row)
            name = _city_name(row)
            if district_id and name:
                rows.append({"district_id": district_id, "city_name": name})
        mapping = _mapping_from_city_rows(_city_rows(payload))
        if mapping:
            _store_city_mapping(mapping)
        return rows


def sync_quick_districts(session: Session) -> dict[str, Any]:
    import asyncio

    carrier = QuickLivraisonCarrier()
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        cities = asyncio.run(carrier.list_cities())
    else:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as pool:
            cities = pool.submit(asyncio.run, carrier.list_cities()).result()
    by_fold = {fold_city(item["city_name"]): item["district_id"] for item in cities}
    updated = 0
    matched = 0
    rows = session.exec(select(CityTarif)).all()
    for row in rows:
        district_id = by_fold.get(fold_city(str(row.city_name or "")))
        if not district_id:
            continue
        matched += 1
        if row.quick_district_id != district_id:
            row.quick_district_id = district_id
            session.add(row)
            updated += 1
    session.commit()
    return {"city_count": len(cities), "matched": matched, "updated": updated}
