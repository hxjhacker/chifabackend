from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx
from sqlalchemy import or_
from sqlmodel import Session, col, select

from app.models import CityTarif
from app.services.meta_livraison_cities import resolve_meta_city

CITIES_URL = "https://gateway.metalivraison.ma/admin-service/public/api/v1/cities"
PAGE_SIZE = 100
FES_SOURCE_CODES = {"FS"}
FES_SOURCE_NAMES = {"FES", "FEZ"}
DEFAULT_DELIVERY_FEE = 35.0
DEFAULT_REFUSAL_FEE = 10.0
DEFAULT_RETURN_FEE = 0.0


def fold_city(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "").replace("\u202c", "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold().replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", value).strip()


def hub_code(raw: str | None) -> str:
    text = re.sub(r"^HUB\s+", "", (raw or "").strip(), flags=re.IGNORECASE).strip()
    return re.sub(r"\s+", " ", text).upper()


def _money(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number < 0:
        return default
    return round(number, 2)


def _is_fes_origin(row: dict[str, Any]) -> bool:
    code = str(row.get("sourceCityCode") or "").strip().upper()
    name = str(row.get("sourceCityName") or "").strip().upper()
    return code in FES_SOURCE_CODES or name in FES_SOURCE_NAMES


@dataclass(frozen=True)
class Tarif:
    meta_city_id: str
    city_name: str
    delivery_fee: float
    refusal_fee: float
    return_fee: float
    hub_name: str


class TarifIndex:
    def __init__(self, rows: Iterable[CityTarif]):
        self.by_fold: dict[str, Tarif] = {}
        self.by_compact: dict[str, Tarif] = {}
        for row in rows:
            tarif = Tarif(
                meta_city_id=str(row.meta_city_id or ""),
                city_name=str(row.city_name or ""),
                delivery_fee=_money(row.delivery_fee, DEFAULT_DELIVERY_FEE),
                refusal_fee=_money(row.refusal_fee, DEFAULT_REFUSAL_FEE),
                return_fee=_money(row.return_fee, DEFAULT_RETURN_FEE),
                hub_name=str(row.hub_name or ""),
            )
            key = fold_city(tarif.city_name)
            if key:
                self.by_fold[key] = tarif
                self.by_compact[key.replace(" ", "")] = tarif

    def find(self, *names: str | None) -> Tarif | None:
        seen: set[str] = set()
        candidates: list[str] = []
        for name in names:
            text = (name or "").strip()
            if text and text not in seen:
                seen.add(text)
                candidates.append(text)
        extra: list[str] = []
        for text in list(candidates):
            official = resolve_meta_city(text)
            if official and official not in seen:
                seen.add(official)
                extra.append(official)
        candidates.extend(extra)
        for name in candidates:
            folded = fold_city(name)
            if not folded:
                continue
            hit = self.by_fold.get(folded) or self.by_compact.get(folded.replace(" ", ""))
            if hit:
                return hit
        return None

    def fees_for(self, *names: str | None) -> tuple[float, float, float]:
        hit = self.find(*names)
        if not hit:
            return DEFAULT_DELIVERY_FEE, DEFAULT_REFUSAL_FEE, DEFAULT_RETURN_FEE
        return hit.delivery_fee, hit.refusal_fee, hit.return_fee

    def hub_for(self, *names: str | None) -> str:
        hit = self.find(*names)
        if not hit:
            return ""
        return hub_code(hit.hub_name)


def load_tarif_index(session: Session) -> TarifIndex:
    return TarifIndex(session.exec(select(CityTarif)).all())


def serialize_tarifs(session: Session) -> list[dict[str, Any]]:
    rows = session.exec(select(CityTarif).order_by(col(CityTarif.city_name))).all()
    return [
        {
            "meta_city_id": row.meta_city_id,
            "city_name": row.city_name,
            "delivery_fee": _money(row.delivery_fee, DEFAULT_DELIVERY_FEE),
            "refusal_fee": _money(row.refusal_fee, DEFAULT_REFUSAL_FEE),
            "return_fee": _money(row.return_fee, DEFAULT_RETURN_FEE),
            "hub_name": row.hub_name or "",
            "hub_code": hub_code(row.hub_name),
            "quick_district_id": getattr(row, "quick_district_id", None),
        }
        for row in rows
    ]


def _lookup_id(row: CityTarif) -> int:
    raw = str(row.meta_city_id or "").strip()
    if raw.isdigit():
        return int(raw)
    return int(row.id.int % 2_147_483_647)


def list_lookup_tarifs(session: Session, search: str = "", limit: int = 50) -> list[dict[str, Any]]:
    cap = max(1, min(int(limit or 50), 200))
    needle = (search or "").strip()
    stmt = select(CityTarif).order_by(col(CityTarif.city_name))
    if needle:
        like = f"%{needle}%"
        stmt = stmt.where(
            or_(
                col(CityTarif.city_name).ilike(like),
                col(CityTarif.hub_name).ilike(like),
            )
        )
    rows = session.exec(stmt.limit(cap)).all()
    return [
        {
            "id": _lookup_id(row),
            "city_name": row.city_name,
            "hub_name": hub_code(row.hub_name) or (row.hub_name or ""),
            "delivery_fee": _money(row.delivery_fee, DEFAULT_DELIVERY_FEE),
            "refusal_fee": _money(row.refusal_fee, DEFAULT_REFUSAL_FEE),
            "return_fee": _money(row.return_fee, DEFAULT_RETURN_FEE),
        }
        for row in rows
    ]


def _parse_record(row: dict[str, Any]) -> dict[str, Any] | None:
    dest_id = row.get("destinationCityId")
    name = str(row.get("destinationCityName") or "").strip()
    if dest_id is None or not name:
        return None
    return {
        "meta_city_id": str(dest_id).strip(),
        "city_name": name[:160],
        "delivery_fee": _money(row.get("deliveryCost"), DEFAULT_DELIVERY_FEE),
        "refusal_fee": _money(row.get("refusalCost"), DEFAULT_REFUSAL_FEE),
        "return_fee": _money(row.get("returnCost"), DEFAULT_RETURN_FEE),
        "hub_name": (str(row.get("destinationZoneName") or "").strip() or None),
    }


def fetch_meta_city_pages(size: int = PAGE_SIZE) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    page = 0
    with httpx.Client(timeout=40.0, follow_redirects=True) as client:
        while True:
            response = client.get(
                CITIES_URL,
                params={
                    "page": page,
                    "size": size,
                    "sortBy": "id",
                    "sortDirection": "desc",
                    "status": "ACTIVE",
                },
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                break
            content = data.get("content") or []
            if not isinstance(content, list) or not content:
                break
            records.extend(item for item in content if isinstance(item, dict))
            total_pages = int(data.get("totalPages") or 0)
            has_next = bool(data.get("hasNext"))
            page += 1
            if not has_next or (total_pages and page >= total_pages):
                break
    return records


def sync_meta_city_tarifs(session: Session) -> dict[str, Any]:
    raw_rows = fetch_meta_city_pages()
    existing = {row.meta_city_id: row for row in session.exec(select(CityTarif)).all()}
    now = datetime.now(timezone.utc)
    upserted = skipped = 0
    seen: set[str] = set()
    for raw in raw_rows:
        if not _is_fes_origin(raw):
            skipped += 1
            continue
        parsed = _parse_record(raw)
        if not parsed:
            skipped += 1
            continue
        meta_id = parsed["meta_city_id"]
        if meta_id in seen:
            continue
        seen.add(meta_id)
        row = existing.get(meta_id)
        if row is None:
            row = CityTarif(meta_city_id=meta_id)
            session.add(row)
            existing[meta_id] = row
        row.city_name = parsed["city_name"]
        row.delivery_fee = parsed["delivery_fee"]
        row.refusal_fee = parsed["refusal_fee"]
        row.return_fee = parsed["return_fee"]
        row.hub_name = parsed["hub_name"]
        row.updated_at = now
        upserted += 1
    session.flush()
    return {
        "fetched": len(raw_rows),
        "upserted": upserted,
        "skipped": skipped,
        "stored": len(existing),
        "source": "FES",
    }


def run_scheduled_city_tarif_sync(force: bool = True) -> None:
    from app.db import engine

    with Session(engine) as session:
        if not force and session.exec(select(CityTarif).limit(1)).first():
            print("[CITY_TARIFS] skip sync, table already populated", flush=True)
            return
        report = sync_meta_city_tarifs(session)
        session.commit()
        print(f"[CITY_TARIFS] synced {report}", flush=True)

