from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.db import get_session
from app.dependencies import get_current_admin
from app.models import DeliveryCity
from app.services.quick_pricing import (
    DEFAULT_COMPETITOR_NAME,
    QUICK_REFUS_PRICE,
    QUICK_RETOUR_PRICE,
    build_stats,
    list_delivery_cities,
    load_pricing_file,
    seed_quick_cities,
    serialize_delivery_city,
)

router = APIRouter(prefix="/api/admin", tags=["admin-pricing"])


class CompetitorPricePatch(BaseModel):
    competitor_delivery_price: float | None = Field(default=None, ge=0, le=9999)
    competitor_retour_price: float | None = Field(default=None, ge=0, le=9999)
    competitor_name: str | None = Field(default=None, max_length=80)


def _pricing_payload() -> dict:
    try:
        return load_pricing_file()
    except Exception:
        return {}


@router.get("/pricing-comparison")
def admin_pricing_comparison(
    q: str = Query(default="", max_length=80),
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    rows = list_delivery_cities(session, search=q)
    payload = _pricing_payload()
    all_rows = rows if not q.strip() else list_delivery_cities(session, search="")
    return {
        "cities": [serialize_delivery_city(row) for row in rows],
        "count": len(rows),
        "stats": build_stats(all_rows, payload),
    }


@router.post("/pricing-comparison/seed")
def admin_seed_pricing_comparison(
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    try:
        return seed_quick_cities(session)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/pricing-comparison/{city_id}")
def admin_patch_pricing_comparison(
    city_id: UUID,
    body: CompetitorPricePatch,
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    row = session.exec(select(DeliveryCity).where(DeliveryCity.id == city_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="city_not_found")
    if body.competitor_delivery_price is not None:
        row.competitor_delivery_price = round(float(body.competitor_delivery_price), 2)
    if body.competitor_retour_price is not None:
        row.competitor_retour_price = round(float(body.competitor_retour_price), 2)
    if body.competitor_name is not None:
        name = body.competitor_name.strip() or DEFAULT_COMPETITOR_NAME
        row.competitor_name = name[:80]
    row.quick_retour_price = QUICK_RETOUR_PRICE
    row.quick_refus_price = QUICK_REFUS_PRICE
    session.add(row)
    session.commit()
    session.refresh(row)
    return serialize_delivery_city(row)
