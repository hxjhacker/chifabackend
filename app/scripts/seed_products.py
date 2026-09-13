from __future__ import annotations

"""Purge leftover catalog rows and seed the 6 production products.

Run from the backend root:
    python -m app.scripts.seed_products
"""

from sqlmodel import Session

from app.db import engine, ensure_order_columns
from app.seed import seed_products


def main() -> None:
    ensure_order_columns()
    with Session(engine) as session:
        result = seed_products(session, reset_stock=True)
    print("Products cleanly initialized.")
    print(result)


if __name__ == "__main__":
    main()
