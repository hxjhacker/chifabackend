from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.db import get_session
from app.dependencies import get_current_admin
from app.models import DeliveryCity
from app.services.carrier_rates import apply_city_rate_patch
from app.services.quick_pricing import (
    DEFAULT_COMPETITOR_NAME,
    META_COMPETITOR_NAME,
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
    quick_delivery_price: float | None = Field(default=None, ge=0, le=9999)
    meta_delivery_fee: float | None = Field(default=None, ge=0, le=9999)


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
    meta_fee = body.meta_delivery_fee if body.meta_delivery_fee is not None else body.competitor_delivery_price
    try:
        patched = apply_city_rate_patch(
            session,
            pricing_city_id=city_id,
            quick_delivery_price=body.quick_delivery_price,
            meta_delivery_fee=meta_fee,
            competitor_retour_price=body.competitor_retour_price,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if body.competitor_name is not None:
        row = session.exec(select(DeliveryCity).where(DeliveryCity.id == city_id)).first()
        if row is not None:
            name = body.competitor_name.strip() or DEFAULT_COMPETITOR_NAME
            if name.casefold() in {"meta", "meta livraison", "metalivraison"}:
                name = META_COMPETITOR_NAME
            row.competitor_name = name[:80]
            session.add(row)
            session.commit()
            session.refresh(row)
            return serialize_delivery_city(row)
    return patched
