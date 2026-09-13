"""Quick pricing comparison table (delivery_cities)."""

from typing import Sequence, Union

from alembic import op

revision: str = "0016_delivery_cities"
down_revision: Union[str, None] = "0015_product_catalog_reorg"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
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
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_delivery_cities_city_key ON delivery_cities (city_key)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_delivery_cities_city_name ON delivery_cities (city_name)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_delivery_cities_search_blob ON delivery_cities (search_blob)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_delivery_cities_search_blob")
    op.execute("DROP INDEX IF EXISTS ix_delivery_cities_city_name")
    op.execute("DROP INDEX IF EXISTS ix_delivery_cities_city_key")
    op.execute("DROP TABLE IF EXISTS delivery_cities")
