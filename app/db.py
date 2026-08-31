from collections.abc import Generator

from sqlalchemy import text
from sqlmodel import Session, create_engine

from app.config import settings

engine = create_engine(
    settings.sqlalchemy_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

ORDER_COLUMN_ALTERS = (
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS address text",
    "ALTER TABLE orders ALTER COLUMN address TYPE text",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS quartier varchar(120)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS street varchar(160)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS building varchar(80)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS landmark varchar(160)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_window varchar(32)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS courier_notes text",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS region_id varchar(8)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS bundle_enabled boolean DEFAULT false",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS secondary_qty integer DEFAULT 1",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS source varchar(32) DEFAULT 'website'",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS confirmed_at timestamptz",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipped_at timestamptz",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivered_at timestamptz",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS cancelled_at timestamptz",
)


def ensure_order_columns() -> None:
    with engine.begin() as conn:
        for sql in ORDER_COLUMN_ALTERS:
            try:
                conn.execute(text(sql))
            except Exception:
                continue


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
