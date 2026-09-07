from __future__ import annotations

from typing import Any

import httpx
from sqlmodel import Session, select

from app.core.config import QUICK_LIVRAISON_API_KEY, QUICK_LIVRAISON_API_URL
from app.db import engine
from app.models import CityTarif
from app.services.carriers.base import ShippingCarrierBase
from app.services.city_tarifs import fold_city
from app.services.pricing import cents_to_mad

EMPTY_KEYS = {"", "YOUR_API_KEY_HERE"}


def _api_key() -> str:
    return (QUICK_LIVRAISON_API_KEY or "").strip()


def _base_url() -> str:
    return (QUICK_LIVRAISON_API_URL or "https://clients.quicklivraison.ma/api").rstrip("/")


def _national_phone(phone: str, phone_national: str) -> str:
    digits = "".join(ch for ch in (phone_national or phone or "") if ch.isdigit())
    if digits.startswith("212") and len(digits) >= 12:
        digits = "0" + digits[3:]
    elif len(digits) == 9 and digits[0] in "567":
        digits = "0" + digits
    return digits


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


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
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            res = await client.post(url, params=self._params(), json=body, headers=self._headers())
        try:
            parsed = res.json()
        except Exception:
            parsed = {"text": res.text}
        return res.status_code, parsed, res.text

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
        phone = _national_phone(str(getattr(order, "phone", "") or ""), str(getattr(order, "phone_national", "") or ""))
        address = " ".join(
            part
            for part in (
                str(getattr(order, "address", "") or "").strip(),
                str(getattr(order, "quartier", "") or "").strip(),
                str(getattr(order, "street", "") or "").strip(),
                str(getattr(order, "city", "") or "").strip(),
            )
            if part
        ).strip()
        payload = {
            "district_id": district_id,
            "city_id": district_id,
            "name": str(getattr(order, "full_name", "") or "").strip(),
            "receiver_name": str(getattr(order, "full_name", "") or "").strip(),
            "phone": phone,
            "tel": phone,
            "address": address,
            "adresse": address,
            "price": cents_to_mad(int(getattr(order, "total_cents", 0) or 0)),
            "cod_amount": cents_to_mad(int(getattr(order, "total_cents", 0) or 0)),
            "comment": str(getattr(order, "courier_notes", "") or "").strip(),
            "note": str(getattr(order, "courier_notes", "") or "").strip(),
            "client_order_ref": str(getattr(order, "id", "") or ""),
            "open_package": 0,
        }
        status_code, parsed, text = await self._post("/deliveries/store", payload)
        tracking = _tracking_from(parsed)
        failed = status_code >= 400 or (isinstance(parsed, dict) and parsed.get("success") is False)
        if failed or not tracking:
            detail = parsed.get("message") if isinstance(parsed, dict) else None
            return {
                "ok": False,
                "tracking_number": tracking,
                "ticket_url": "",
                "carrier": self.carrier_id,
                "error": detail or text or "quick_livraison_failed",
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
