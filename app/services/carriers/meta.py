from __future__ import annotations

from typing import Any

from app.services.carriers.base import ShippingCarrierBase
from app.services.meta_livraison import configured, create_colis, get_order_status_from_meta


class MetaLivraisonCarrier(ShippingCarrierBase):
    carrier_id = "meta_livraison"
    carrier_name = "Meta Livraison"

    def is_configured(self) -> bool:
        return configured()

    async def create_shipment(self, order: Any) -> dict[str, Any]:
        result = create_colis(order)
        if not result.get("ok"):
            detail = result.get("detail") if result.get("detail") not in (None, "") else result.get("text")
            return {
                "ok": False,
                "tracking_number": "",
                "ticket_url": "",
                "carrier": self.carrier_id,
                "error": detail or "meta_livraison_failed",
                "raw": result,
            }
        code = str(result.get("code") or "").strip()
        return {
            "ok": True,
            "tracking_number": code,
            "ticket_url": str(result.get("ticket_url") or "").strip(),
            "carrier": self.carrier_id,
            "error": "",
            "raw": result,
        }

    async def get_tracking_status(self, tracking_number: str) -> dict[str, Any]:
        result = get_order_status_from_meta(tracking_number)
        status = str(result.get("status") or "") if result.get("ok") else ""
        return {
            "ok": bool(result.get("ok") and status),
            "status": status or "",
            "raw": result.get("raw") or status,
            "error": result.get("error") or "",
            "carrier": self.carrier_id,
        }

    async def cancel_shipment(self, tracking_number: str) -> bool:
        _ = tracking_number
        return False
