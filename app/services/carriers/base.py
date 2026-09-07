from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ShippingCarrierBase(ABC):
    carrier_id: str
    carrier_name: str

    def is_configured(self) -> bool:
        return True

    @abstractmethod
    async def create_shipment(self, order: Any) -> dict[str, Any]:
        """Creates shipment on carrier and returns dict with tracking_number and details."""

    @abstractmethod
    async def get_tracking_status(self, tracking_number: str) -> dict[str, Any]:
        """Returns normalized status: 'in_shipping', 'delivered', 'returned', 'cancelled'."""

    @abstractmethod
    async def cancel_shipment(self, tracking_number: str) -> bool:
        pass
