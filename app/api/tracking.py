from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel

from app.services.capi import CapiUser, dispatch_capi

router = APIRouter(prefix="/api")


class TrackingIn(BaseModel):
    event_name: str
    event_id: str
    event_source_url: str | None = None
    value: float | None = None
    currency: str = "MAD"
    content_ids: list[str] = []
    phone: str | None = None
    city: str | None = None
    email: str | None = None
    full_name: str | None = None
    fbp: str | None = None
    fbc: str | None = None
    ttclid: str | None = None
    sccid: str | None = None


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


@router.post("/tracking/events")
async def track_event(payload: TrackingIn, request: Request, background: BackgroundTasks):
    user = CapiUser(
        phone_e164=payload.phone,
        full_name=payload.full_name,
        city=payload.city,
        email=payload.email,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        fbp=payload.fbp,
        fbc=payload.fbc,
        ttclid=payload.ttclid,
        sccid=payload.sccid,
        event_source_url=payload.event_source_url or "",
    )
    background.add_task(
        dispatch_capi,
        event_name=payload.event_name,
        event_id=payload.event_id,
        user=user,
        value=payload.value,
        content_ids=payload.content_ids,
    )
    return {"ok": True, "event_id": payload.event_id}
