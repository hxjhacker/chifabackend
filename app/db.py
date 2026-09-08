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
    "ALTER TABLE orders ALTER COLUMN address TYPE text USING address::text",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS quartier varchar(120)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS street varchar(160)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS building varchar(80)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS landmark varchar(160)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_window varchar(32)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS courier_notes text",
    "ALTER TABLE orders ALTER COLUMN courier_notes TYPE text USING courier_notes::text",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS region_id varchar(32)",
    "ALTER TABLE orders ALTER COLUMN region_id TYPE varchar(32)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS bundle_enabled boolean DEFAULT false",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS secondary_qty integer DEFAULT 1",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS source varchar(32) DEFAULT 'website'",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS confirmed_at timestamptz",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipped_at timestamptz",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivered_at timestamptz",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS cancelled_at timestamptz",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS meta_livraison_code varchar(80)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS meta_livraison_sent_at timestamptz",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS meta_livraison_ticket_url text",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_city varchar(160)",
    "ALTER TABLE orders ALTER COLUMN city TYPE varchar(160)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS carrier varchar(50) DEFAULT 'meta_livraison' NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_orders_carrier ON orders (carrier)",
)

PAGE_VIEWS_SQL = (
    """
    CREATE TABLE IF NOT EXISTS page_views (
      id uuid PRIMARY KEY,
      kind varchar(32) NOT NULL,
      product_slug varchar(32),
      path text,
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_page_views_created_at ON page_views (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_page_views_slug_created ON page_views (product_slug, created_at)",
)

PUSH_SUBSCRIPTIONS_SQL = (
    """
    CREATE TABLE IF NOT EXISTS push_subscriptions (
      id uuid PRIMARY KEY,
      endpoint text NOT NULL UNIQUE,
      p256dh text NOT NULL,
      auth text NOT NULL,
      user_agent text,
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_push_subscriptions_endpoint ON push_subscriptions (endpoint)",
)

CITY_TARIFS_SQL = (
    """
    CREATE TABLE IF NOT EXISTS city_tarifs (
      id uuid PRIMARY KEY,
      meta_city_id varchar(32) NOT NULL,
      city_name varchar(160) NOT NULL,
      delivery_fee double precision NOT NULL DEFAULT 35,
      refusal_fee double precision NOT NULL DEFAULT 10,
      return_fee double precision NOT NULL DEFAULT 0,
      hub_name varchar(120),
      quick_district_id integer,
      updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_city_tarifs_meta_city_id ON city_tarifs (meta_city_id)",
    "CREATE INDEX IF NOT EXISTS ix_city_tarifs_city_name ON city_tarifs (city_name)",
    "ALTER TABLE city_tarifs ADD COLUMN IF NOT EXISTS quick_district_id integer",
    "CREATE INDEX IF NOT EXISTS ix_city_tarifs_quick_district_id ON city_tarifs (quick_district_id)",
)

PRODUCTS_SQL = (
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS code varchar(64)",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS default_price_cents integer DEFAULT 0 NOT NULL",
    "UPDATE products SET code = UPPER(slug) WHERE code IS NULL OR BTRIM(code) = ''",
    "UPDATE products SET default_price_cents = 19900 WHERE slug = 'quran' AND (default_price_cents IS NULL OR default_price_cents = 0)",
    "UPDATE products SET default_price_cents = 14900 WHERE slug = 'kids' AND (default_price_cents IS NULL OR default_price_cents = 0)",
    "UPDATE products SET default_price_cents = 19900 WHERE slug IN ('music', 'educative') AND (default_price_cents IS NULL OR default_price_cents = 0)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_products_code ON products (code)",
    "ALTER TABLE products ALTER COLUMN code SET NOT NULL",
)


def _exec_isolated(conn, sql: str) -> None:
    """Run one statement in a savepoint so a failure cannot abort the batch."""
    try:
        conn.execute(text("SAVEPOINT schema_stmt"))
        conn.execute(text(sql))
        conn.execute(text("RELEASE SAVEPOINT schema_stmt"))
    except Exception:
        try:
            conn.execute(text("ROLLBACK TO SAVEPOINT schema_stmt"))
        except Exception:
            pass


def ensure_order_columns() -> None:
    with engine.begin() as conn:
        for sql in ORDER_COLUMN_ALTERS:
            _exec_isolated(conn, sql)
        for sql in PAGE_VIEWS_SQL:
            _exec_isolated(conn, sql)
        for sql in PUSH_SUBSCRIPTIONS_SQL:
            _exec_isolated(conn, sql)
        for sql in CITY_TARIFS_SQL:
            _exec_isolated(conn, sql)
        for sql in PRODUCTS_SQL:
            _exec_isolated(conn, sql)


def get_session() -> Generator[Session, None, None]:
    session: Session | None = None
    try:
        session = Session(engine)
        yield session
    except Exception:
        if session is not None:
            try:
                session.rollback()
            except Exception:
                pass
        raise
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
