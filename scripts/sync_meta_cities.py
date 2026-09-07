#!/usr/bin/env python3
"""Fetch official Meta Livraison city tariffs and upsert them into city_tarifs."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlmodel import SQLModel, Session

from app.db import engine, ensure_order_columns
from app.models import CityTarif  # noqa: F401
from app.services.city_tarifs import sync_meta_city_tarifs


def main() -> int:
    SQLModel.metadata.create_all(engine)
    ensure_order_columns()
    with Session(engine) as session:
        report = sync_meta_city_tarifs(session)
        session.commit()
    print(
        "city_tarifs sync: "
        f"fetched={report['fetched']} upserted={report['upserted']} "
        f"skipped={report['skipped']} stored={report['stored']} source={report['source']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
