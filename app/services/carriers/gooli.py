from __future__ import annotations

from typing import Any

from sqlmodel import Session

from app.db import engine
from app.services.carriers.base import ShippingCarrierBase
from app.services.gooli import build_order, configured, parse_created, parse_errors, format_errors
from app.services.gooli import _post


class GooliCarrier(ShippingCarrierBase):
    carrier_id = "gooli"
    carrier_name = "Gooli Express"

    def is_configured(self) -> bool:
        return configured()

    async def create_shipment(self, order: Any) -> dict[str, Any]:
        if not configured():
            return {"ok": False, "tracking_number": "", "ticket_url": "", "carrier": self.carrier_id, "error": "gooli_not_configured", "raw": None}
        with Session(engine) as session:
            built = build_order(session, order)
        if "error" in built:
            return {"ok": False, "tracking_number": "", "ticket_url": "", "carrier": self.carrier_id, "error": built["error"], "raw": built}
        status, payload = _post([built["payload"]])
        created = parse_created(payload)
        tracking = created[0]["tracking_code"] if created else ""
        if status in (200, 201) and tracking:
            return {"ok": True, "tracking_number": tracking, "ticket_url": "", "carrier": self.carrier_id, "error": "", "raw": payload}
        message = format_errors(parse_errors(payload)) or f"رفض Gooli الإرسال ({status})."
        return {"ok": False, "tracking_number": "", "ticket_url": "", "carrier": self.carrier_id, "error": message, "raw": payload}

    async def get_tracking_status(self, tracking_number: str, **kwargs: Any) -> dict[str, Any]:
        _ = tracking_number, kwargs
        return {
            "ok": False,
            "status": "",
            "raw": "",
            "error": "gooli_webhook_only",
            "carrier": self.carrier_id,
        }

    async def cancel_shipment(self, tracking_number: str) -> bool:
        _ = tracking_number
        return False
