from __future__ import annotations

"""Seed Quick Livraison city prices into delivery_cities.

Run from the backend root:
    python -m app.scripts.seed_quick_cities
"""

from sqlmodel import Session

from app.db import engine, ensure_order_columns
from app.services.quick_pricing import PRICING_JSON, seed_quick_cities


def main() -> None:
    ensure_order_columns()
    with Session(engine) as session:
        result = seed_quick_cities(session)
    print("Quick pricing cities seeded.")
    print(f"source_file={PRICING_JSON}")
    print(result)
    print(f"TOTAL_CITIES_SEEDED={result.get('total', 0)}")


if __name__ == "__main__":
    main()
