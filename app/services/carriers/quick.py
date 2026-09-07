from __future__ import annotations

from typing import Any

import httpx
from sqlmodel import Session, select

from app.core.config import QUICK_LIVRAISON_API_KEY, QUICK_LIVRAISON_API_URL
from app.db import engine
from app.models import CityTarif
from app.services.carriers.base import ShippingCarrierBase
from app.services.city_tarifs import fold_city

EMPTY_KEYS = {"", "YOUR_API_KEY_HERE"}


def _api_key() -> str:
    return (QUICK_LIVRAISON_API_KEY or "").strip()


def _base_url() -> str:
    return (QUICK_LIVRAISON_API_URL or "https://clients.quicklivraison.ma/api").rstrip("/")


PACK_NAMES = {
    "quran": "مصحف شيفا جلو",
    "educative": "حصيرة تعليمية",
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


def _tracking_from(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in (
            "tracking_number",
            "trackingNumber",
            "tracking",
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
    for key in ("status", "etat", "state", "statut", "parcel_status", "last_status"):
        value = payload.get(key)
        if value not in (None, ""):
            if isinstance(value, dict):
                return str(value.get("name") or value.get("label") or value.get("code") or "")
            return str(value)
    nested = payload.get("data") or payload.get("parcel") or payload.get("delivery")
    if isinstance(nested, dict):
        return _status_from(nested)
    return ""


def normalize_quick_status(raw: str) -> str | None:
    folded = (raw or "").casefold().replace("-", " ").replace("_", " ")
    if not folded:
        return None
    if any(token in folded for token in ("retour", "return", "مرتجع")):
        return "returned"
    if any(token in folded for token in ("annul", "cancel", "refus", "ملغ")):
        return "cancelled"
    if any(token in folded for token in ("livre", "delivered", "تم التسليم", "تم التوصيل")):
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
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            res = await client.get(url, params=self._params(), headers=self._headers())
        try:
            return res.json()
        except Exception:
            return {"ok": False, "status": res.status_code, "text": res.text}

    async def _post(self, path: str, payload: dict[str, Any]) -> tuple[int, Any, str]:
        url = f"{_base_url()}{path}"
        body = {**payload, "api_key": _api_key()}
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
            res = await client.post(url, params=self._params(), json=body, headers=self._headers())
        parsed = _parse_http_body(res)
        return res.status_code, parsed, res.text

    async def _post_store(self, payload: dict[str, Any]) -> tuple[int, Any, str]:
        """Create a parcel: form-urlencoded first (Quick cURL), then JSON if montant is still rejected."""
        url = f"{_base_url()}/deliveries/store"
        body = {**payload, "api_key": _api_key()}
        accept = {"Accept": "application/json"}
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
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

    def _district_from_db(self, order: Any) -> int | None:
        names = [
            str(getattr(order, "shipping_city", "") or "").strip(),
            str(getattr(order, "city", "") or "").strip(),
        ]
        keys = [fold_city(name) for name in names if name]
        if not keys:
            return None
        with Session(engine) as session:
            rows = session.exec(select(CityTarif)).all()
            by_fold = {fold_city(str(row.city_name or "")): row for row in rows if row.city_name}
            for key in keys:
                hit = by_fold.get(key) or by_fold.get(key.replace(" ", ""))
                if hit and hit.quick_district_id:
                    return int(hit.quick_district_id)
        return None

    async def resolve_district_id(self, order: Any) -> int | None:
        stored = self._district_from_db(order)
        if stored:
            return stored
        payload = await self._get("/getCityIDs")
        wanted = {fold_city(str(getattr(order, name, "") or "")) for name in ("shipping_city", "city")}
        wanted.discard("")
        for row in _city_rows(payload):
            name = fold_city(_city_name(row))
            if name and name in wanted:
                return _district_id(row)
        return None

    async def create_shipment(self, order: Any) -> dict[str, Any]:
        if not self.is_configured():
            return {
                "ok": False,
                "tracking_number": "",
                "ticket_url": "",
                "carrier": self.carrier_id,
                "error": "quick_livraison_not_configured",
            }
        district_id = await self.resolve_district_id(order)
        if not district_id:
            return {
                "ok": False,
                "tracking_number": "",
                "ticket_url": "",
                "carrier": self.carrier_id,
                "error": "quick_district_not_mapped",
            }
        phone = _national_phone(
            str(getattr(order, "phone", "") or ""),
            str(getattr(order, "phone_national", "") or ""),
        )
        city = str(getattr(order, "city", "") or getattr(order, "shipping_city", "") or "").strip()
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
        payload = {
            "district_id": int(district_id),
            "city_id": int(district_id),
            "name": name,
            "receiver_name": name,
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
            "qte_prd": _qty(order),
            "comment": str(getattr(order, "courier_notes", "") or "").strip(),
            "note": str(getattr(order, "courier_notes", "") or "").strip(),
            "client_order_ref": code,
            "open_package": 1,
        }
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
        return {
            "ok": True,
            "tracking_number": tracking,
            "ticket_url": "",
            "carrier": self.carrier_id,
            "error": "",
            "raw": parsed,
        }

    async def get_tracking_status(self, tracking_number: str) -> dict[str, Any]:
        code = str(tracking_number or "").strip()
        if not code:
            return {"ok": False, "status": "", "raw": "", "error": "missing_tracking_code", "carrier": self.carrier_id}
        payload = await self._get(f"/getParcelDetails/{code}")
        raw = _status_from(payload)
        status = normalize_quick_status(raw)
        return {
            "ok": bool(status),
            "status": status or "",
            "raw": raw,
            "error": "" if status else "unknown_status",
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
