from __future__ import annotations

import httpx
from fastapi import APIRouter

from app.config import settings

router = APIRouter(prefix="/api", tags=["meta"])

EMPTY = {
    "spend": 0.0,
    "clicks": 0,
    "impressions": 0,
    "cpc": 0.0,
    "cpm": 0.0,
    "ctr": 0.0,
}


def _num(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


@router.get("/meta-insights")
def meta_insights():
    account_id = (settings.meta_ad_account_id or "").strip()
    token = (settings.meta_access_token or "").strip()
    if not account_id or not token:
        return {**EMPTY, "detail": "meta_not_configured"}

    url = f"https://graph.facebook.com/v26.0/{account_id}/insights"
    params = {
        "fields": "spend,impressions,clicks,cpc,cpm,ctr",
        "date_preset": "today",
        "access_token": token,
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            res = client.get(url, params=params)
        payload = res.json()
        print("Meta API Response:", payload)
        if res.status_code >= 400:
            return {**EMPTY, "detail": "meta_insights_failed"}
        rows = payload.get("data") or []
        if not rows:
            return EMPTY
        row = rows[0]
        return {
            "spend": _num(row.get("spend")),
            "clicks": int(round(_num(row.get("clicks")))),
            "impressions": int(round(_num(row.get("impressions")))),
            "cpc": _num(row.get("cpc")),
            "cpm": _num(row.get("cpm")),
            "ctr": _num(row.get("ctr")),
        }
    except Exception as err:
        print("meta_insights_failed", err)
        return {**EMPTY, "detail": "meta_insights_failed"}
