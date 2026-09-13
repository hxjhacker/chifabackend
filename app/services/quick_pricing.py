from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import or_
from sqlmodel import Session, col, select

from app.models import CityTarif, DeliveryCity, utcnow
from app.services.city_tarifs import fold_city

PRICING_JSON = Path(__file__).resolve().parents[1] / "data" / "quick_pricing.json"
QUICK_RETOUR_PRICE = 0.0
QUICK_REFUS_PRICE = 0.0
DEFAULT_COMPETITOR_DELIVERY = 35.0
DEFAULT_COMPETITOR_RETOUR = 15.0
DEFAULT_COMPETITOR_NAME = "ناقل بديل"
META_COMPETITOR_NAME = "Meta Livraison"

AR_ALIASES: dict[str, str] = {
    "casablanca": "الدار البيضاء",
    "casa": "الدار البيضاء",
    "rabat": "الرباط",
    "sale": "سلا",
    "salé": "سلا",
    "temara": "تمارة",
    "témara": "تمارة",
    "skhirat": "الصخيرات",
    "mohammedia": "المحمدية",
    "fes": "فاس",
    "fez": "فاس",
    "fès": "فاس",
    "meknes": "مكناس",
    "meknès": "مكناس",
    "marrakech": "مراكش",
    "marrakesh": "مراكش",
    "tanger": "طنجة",
    "tangier": "طنجة",
    "tetouan": "تطوان",
    "tétouan": "تطوان",
    "agadir": "أكادير",
    "oujda": "وجدة",
    "nador": "الناظور",
    "kenitra": "القنيطرة",
    "kénitra": "القنيطرة",
    "el jadida": "الجديدة",
    "jadida": "الجديدة",
    "safi": "آسفي",
    "khouribga": "خريبكة",
    "beni mellal": "بني ملال",
    "beni-mellal": "بني ملال",
    "taza": "تازة",
    "larache": "العرائش",
    "khemisset": "الخميسات",
    "khémisset": "الخميسات",
    "settat": "سطات",
    "berrechid": "برشيد",
    "laayoune": "العيون",
    "laâyoune": "العيون",
    "dakhla": "الداخلة",
    "errachidia": "الراشيدية",
    "ouarzazate": "ورزازات",
    "ifrane": "إفران",
    "alhoceima": "الحسيمة",
    "al hoceima": "الحسيمة",
    "al-hoceima": "الحسيمة",
    "essaouira": "الصويرة",
    "taroudant": "تارودانت",
    "tiznit": "تيزنيت",
    "guelmim": "كلميم",
    "tan tan": "طانطان",
    "midelt": "ميدلت",
    "azilal": "أزيلال",
    "khenifra": "خنيفرة",
    "khénifra": "خنيفرة",
    "sidi kacem": "سيدي قاسم",
    "sidi slimane": "سيدي سليمان",
    "berkane": "بركان",
    "taourirt": "تاوريرت",
    "figuig": "فكيك",
    "ouezzane": "وزان",
    "chefchaouen": "شفشاون",
    "fnideq": "الفنيدق",
    "martil": "مرتيل",
    "mdiq": "المضيق",
    "m'diq": "المضيق",
    "ain harouda": "عين حرودة",
    "tit mellil": "تيط مليل",
    "lahraouiyine": "الهراويين",
    "bouskoura": "بوسكورة",
    "nouaceur": "النواصر",
    "mediouna": "مديونة",
    "dar bouazza": "دار بوعزة",
}


def _money(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number < 0:
        return default
    return round(number, 2)


def _has_arabic(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text or ""))


def _arabic_name(city: str, meta_name: str = "") -> str:
    if _has_arabic(meta_name):
        return meta_name.strip()
    folded = fold_city(city)
    if folded in AR_ALIASES:
        return AR_ALIASES[folded]
    compact = folded.replace(" ", "")
    for key, label in AR_ALIASES.items():
        if key.replace(" ", "") == compact:
            return label
    return ""


def _search_blob(city_name: str, city_name_ar: str, city_key: str) -> str:
    parts = [city_name, city_name_ar, city_key, city_name.casefold()]
    return " ".join(part.strip() for part in parts if part and part.strip())[:400]


def load_pricing_file(path: Path | None = None) -> dict[str, Any]:
    target = path or PRICING_JSON
    if not target.is_file():
        raise FileNotFoundError(f"quick_pricing.json missing: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("quick_pricing.json must be an object")
    cities = payload.get("cities")
    if not isinstance(cities, list):
        raise ValueError("quick_pricing.json is missing cities[]")
    return payload


def _meta_index(session: Session) -> dict[str, CityTarif]:
    index: dict[str, CityTarif] = {}
    for row in session.exec(select(CityTarif)).all():
        key = fold_city(row.city_name)
        if not key:
            continue
        index[key] = row
        index[key.replace(" ", "")] = row
    return index


def _match_meta(index: dict[str, CityTarif], city: str) -> CityTarif | None:
    key = fold_city(city)
    if not key:
        return None
    return index.get(key) or index.get(key.replace(" ", ""))


def serialize_delivery_city(row: DeliveryCity) -> dict[str, Any]:
    quick_delivery = _money(row.quick_delivery_price)
    competitor_delivery = None if row.competitor_delivery_price is None else _money(row.competitor_delivery_price)
    competitor_retour = _money(row.competitor_retour_price, DEFAULT_COMPETITOR_RETOUR)
    quick_total = round(quick_delivery + QUICK_RETOUR_PRICE, 2)
    competitor_total = None if competitor_delivery is None else round(competitor_delivery + competitor_retour, 2)
    cheaper = "unknown"
    savings = None
    if competitor_total is not None:
        savings = round(competitor_total - quick_total, 2)
        if savings > 0:
            cheaper = "quick"
        elif savings < 0:
            cheaper = "competitor"
        else:
            cheaper = "tie"
    return {
        "id": str(row.id),
        "city_key": row.city_key,
        "city_name": row.city_name,
        "city_name_ar": row.city_name_ar or "",
        "delivery_delay": (row.delivery_delay or "").strip() or None,
        "quick_delivery_price": quick_delivery,
        "quick_retour_price": QUICK_RETOUR_PRICE,
        "quick_refus_price": QUICK_REFUS_PRICE,
        "competitor_name": (row.competitor_name or DEFAULT_COMPETITOR_NAME).strip() or DEFAULT_COMPETITOR_NAME,
        "competitor_delivery_price": competitor_delivery,
        "competitor_retour_price": competitor_retour,
        "quick_total": quick_total,
        "competitor_total": competitor_total,
        "savings": savings,
        "cheaper": cheaper,
    }


def build_stats(rows: list[DeliveryCity], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    prices = [_money(row.quick_delivery_price) for row in rows]
    avg = round(sum(prices) / len(prices), 2) if prices else 0.0
    file_count = 0
    if payload and isinstance(payload.get("count"), int):
        file_count = payload["count"]
    elif payload and isinstance(payload.get("cities"), list):
        file_count = len(payload["cities"])
    return {
        "total_cities": len(rows),
        "file_cities": file_count or len(rows),
        "average_delivery_rate": avg,
        "quick_retour_price": QUICK_RETOUR_PRICE,
        "quick_refus_price": QUICK_REFUS_PRICE,
        "advantage": "ميزة QuickLivraison: الارجاع (Retour) والرفض (Refus) مجاني 0 درهم لجميع المدن",
        "source": (payload or {}).get("source") or "https://quicklivraison.ma/pricing",
        "scraped_at": (payload or {}).get("scraped_at"),
    }


def list_delivery_cities(session: Session, search: str = "") -> list[DeliveryCity]:
    stmt = select(DeliveryCity).order_by(col(DeliveryCity.city_name))
    needle = (search or "").strip()
    if needle:
        like = f"%{needle}%"
        stmt = stmt.where(
            or_(
                col(DeliveryCity.city_name).ilike(like),
                col(DeliveryCity.city_name_ar).ilike(like),
                col(DeliveryCity.search_blob).ilike(like),
            )
        )
    return list(session.exec(stmt).all())


def seed_quick_cities(session: Session, path: Path | None = None) -> dict[str, Any]:
    payload = load_pricing_file(path)
    cities = payload.get("cities") or []
    meta = _meta_index(session)
    existing = {row.city_key: row for row in session.exec(select(DeliveryCity)).all()}
    created = 0
    updated = 0
    skipped = 0
    seen: set[str] = set()

    for item in cities:
        if not isinstance(item, dict):
            skipped += 1
            continue
        city_name = str(item.get("city") or "").strip()
        city_key = fold_city(city_name)
        if not city_name or not city_key or city_key in seen:
            skipped += 1
            continue
        seen.add(city_key)
        delay_raw = item.get("delivery_delay")
        delay = str(delay_raw).strip() if delay_raw not in (None, "") else None
        quick_price = _money(item.get("delivery_price_mad"))
        matched = _match_meta(meta, city_name)
        arabic = _arabic_name(city_name, matched.city_name if matched else "")
        competitor_delivery = (
            _money(matched.delivery_fee, DEFAULT_COMPETITOR_DELIVERY) if matched else DEFAULT_COMPETITOR_DELIVERY
        )
        competitor_name = META_COMPETITOR_NAME if matched else DEFAULT_COMPETITOR_NAME
        row = existing.get(city_key)
        if row is None:
            row = DeliveryCity(
                city_key=city_key,
                city_name=city_name,
                city_name_ar=arabic,
                search_blob=_search_blob(city_name, arabic, city_key),
                delivery_delay=delay,
                quick_delivery_price=quick_price,
                quick_retour_price=QUICK_RETOUR_PRICE,
                quick_refus_price=QUICK_REFUS_PRICE,
                competitor_name=competitor_name,
                competitor_delivery_price=competitor_delivery,
                competitor_retour_price=DEFAULT_COMPETITOR_RETOUR,
            )
            session.add(row)
            existing[city_key] = row
            created += 1
            continue
        row.city_name = city_name
        if arabic and not row.city_name_ar:
            row.city_name_ar = arabic
        row.search_blob = _search_blob(row.city_name, row.city_name_ar, city_key)
        row.delivery_delay = delay
        row.quick_delivery_price = quick_price
        row.quick_retour_price = QUICK_RETOUR_PRICE
        row.quick_refus_price = QUICK_REFUS_PRICE
        if row.competitor_delivery_price is None:
            row.competitor_delivery_price = competitor_delivery
        if not (row.competitor_name or "").strip():
            row.competitor_name = competitor_name
        row.updated_at = utcnow()
        updated += 1

    session.commit()
    total = session.exec(select(DeliveryCity)).all()
    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "total": len(total),
        "file_cities": int(payload.get("count") or len(cities)),
        "source": payload.get("source"),
        "scraped_at": payload.get("scraped_at"),
    }
