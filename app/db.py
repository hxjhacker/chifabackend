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
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS carrier_status varchar(50)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS dispatched_at timestamptz",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_cost double precision",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS assigned_team_member_id varchar(64) DEFAULT 'mohammed'",
    "UPDATE orders SET assigned_team_member_id = 'mohammed' WHERE assigned_team_member_id IS NULL OR BTRIM(assigned_team_member_id) = ''",
    "CREATE INDEX IF NOT EXISTS ix_orders_assigned_team_member_id ON orders (assigned_team_member_id)",
    "CREATE INDEX IF NOT EXISTS ix_orders_carrier ON orders (carrier)",
    "CREATE INDEX IF NOT EXISTS ix_orders_created_at ON orders (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_orders_confirmed_at ON orders (confirmed_at)",
    "CREATE INDEX IF NOT EXISTS ix_orders_meta_livraison_code ON orders (meta_livraison_code)",
    """
    CREATE INDEX IF NOT EXISTS ix_orders_undispatched_status_created
    ON orders (status, created_at DESC)
    WHERE COALESCE(BTRIM(meta_livraison_code), '') = ''
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_orders_undispatched_confirmed
    ON orders (confirmed_at)
    WHERE COALESCE(BTRIM(meta_livraison_code), '') = ''
    """,
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

DELIVERY_CITIES_SQL = (
    """
    CREATE TABLE IF NOT EXISTS delivery_cities (
      id uuid PRIMARY KEY,
      city_key varchar(180) NOT NULL,
      city_name varchar(160) NOT NULL,
      city_name_ar varchar(160) NOT NULL DEFAULT '',
      search_blob varchar(400) NOT NULL DEFAULT '',
      delivery_delay varchar(40),
      quick_delivery_price double precision NOT NULL DEFAULT 0,
      quick_retour_price double precision NOT NULL DEFAULT 0,
      quick_refus_price double precision NOT NULL DEFAULT 0,
      competitor_name varchar(80) NOT NULL DEFAULT 'ناقل بديل',
      competitor_delivery_price double precision,
      competitor_retour_price double precision NOT NULL DEFAULT 15,
      updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_delivery_cities_city_key ON delivery_cities (city_key)",
    "CREATE INDEX IF NOT EXISTS ix_delivery_cities_city_name ON delivery_cities (city_name)",
    "CREATE INDEX IF NOT EXISTS ix_delivery_cities_search_blob ON delivery_cities (search_blob)",
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
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS quick_product_id integer",
    "CREATE INDEX IF NOT EXISTS ix_products_quick_product_id ON products (quick_product_id)",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS category varchar(32) DEFAULT 'standard' NOT NULL",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_quick_stock boolean DEFAULT false NOT NULL",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS stock_quantity integer DEFAULT 0 NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_products_category ON products (category)",
    "CREATE INDEX IF NOT EXISTS ix_products_is_quick_stock ON products (is_quick_stock)",
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
        for sql in DELIVERY_CITIES_SQL:
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
