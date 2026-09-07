from __future__ import annotations

from typing import Any

from app.core.config import FORCELOG_API_KEY, FORCELOG_API_URL
from app.services.carriers.base import ShippingCarrierBase


class ForceLogCarrier(ShippingCarrierBase):
    """Scaffold only — Force Log credentials and endpoints are reserved for a later integration."""

    carrier_id = "force_log"
    carrier_name = "Force Log"

    def is_configured(self) -> bool:
        return bool(FORCELOG_API_KEY and FORCELOG_API_URL)

    async def create_shipment(self, order: Any) -> dict[str, Any]:
        _ = order
        return {
            "ok": False,
            "tracking_number": "",
            "ticket_url": "",
            "carrier": self.carrier_id,
            "error": "force_log_not_implemented",
            "raw": {"api_url": FORCELOG_API_URL},
        }

    async def get_tracking_status(self, tracking_number: str) -> dict[str, Any]:
        _ = tracking_number
        return {
            "ok": False,
            "status": "",
            "raw": "",
            "error": "force_log_not_implemented",
            "carrier": self.carrier_id,
        }

    async def cancel_shipment(self, tracking_number: str) -> bool:
        _ = tracking_number
        return False
