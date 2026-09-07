from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.services.carriers.base import ShippingCarrierBase
from app.services.carriers.force_log import ForceLogCarrier
from app.services.carriers.meta import MetaLivraisonCarrier
from app.services.carriers.quick import QuickLivraisonCarrier

CARRIER_META = "meta_livraison"
CARRIER_QUICK = "quick_livraison"
CARRIER_FORCE = "force_log"
DEFAULT_CARRIER = CARRIER_META
ALLOWED_CARRIERS = (CARRIER_META, CARRIER_QUICK, CARRIER_FORCE)

CARRIER_LABELS = {
    CARRIER_META: "Meta Livraison",
    CARRIER_QUICK: "Quick Livraison",
    CARRIER_FORCE: "Force Log",
}

_FACTORIES: dict[str, type[ShippingCarrierBase]] = {
    CARRIER_META: MetaLivraisonCarrier,
    CARRIER_QUICK: QuickLivraisonCarrier,
    CARRIER_FORCE: ForceLogCarrier,
}


def normalize_carrier(value: str | None) -> str:
    raw = str(value or DEFAULT_CARRIER).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "meta": CARRIER_META,
        "metalivraison": CARRIER_META,
        "quick": CARRIER_QUICK,
        "quicklivraison": CARRIER_QUICK,
        "force": CARRIER_FORCE,
        "forcelog": CARRIER_FORCE,
    }
    resolved = aliases.get(raw, raw)
    return resolved if resolved in ALLOWED_CARRIERS else DEFAULT_CARRIER


def get_carrier(carrier_id: str | None = None) -> ShippingCarrierBase:
    return _FACTORIES[normalize_carrier(carrier_id)]()


def carrier_catalog() -> list[dict[str, Any]]:
    rows = []
    for carrier_id in ALLOWED_CARRIERS:
        adapter = get_carrier(carrier_id)
        rows.append(
            {
                "id": adapter.carrier_id,
                "name": adapter.carrier_name,
                "configured": adapter.is_configured(),
                "active": adapter.carrier_id != CARRIER_FORCE and adapter.is_configured(),
                "scaffolded": adapter.carrier_id == CARRIER_FORCE,
            }
        )
    return rows


def run_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
