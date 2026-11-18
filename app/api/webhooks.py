from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app.db import engine
from app.services.gooli import apply_webhook

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/gooli")
async def gooli_webhook(request: Request):
    raw = await request.body()
    signature = request.headers.get("x-webhook-signature") or request.headers.get("x-gooli-signature") or ""
    timestamp = request.headers.get("x-webhook-timestamp") or request.headers.get("x-gooli-timestamp") or request.headers.get("x-timestamp") or ""
    event_id = request.headers.get("x-webhook-id") or request.headers.get("x-request-id") or request.headers.get("x-gooli-event-id") or ""
    try:
        with Session(engine) as session:
            body = apply_webhook(session, raw, signature, timestamp, event_id)
        return JSONResponse(body, status_code=200)
    except Exception as exc:
        status = getattr(exc, "status_code", None) or 500
        detail = getattr(exc, "detail", None) or "webhook_failed"
        if status == 500:
            return JSONResponse({"ok": False, "error": "webhook_failed"}, status_code=500)
        return JSONResponse({"ok": False, "error": detail}, status_code=int(status))
