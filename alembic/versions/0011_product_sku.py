"""Product SKU / default price columns for admin catalog."""

from typing import Sequence, Union

from alembic import op

revision: str = "0011_product_sku"
down_revision: Union[str, None] = "0010_multi_carrier"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS code varchar(64)")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS default_price_cents integer DEFAULT 0 NOT NULL")
    op.execute("UPDATE products SET code = UPPER(slug) WHERE code IS NULL OR BTRIM(code) = ''")
    op.execute(
        "UPDATE products SET code = 'PRD-' || UPPER(SUBSTRING(REPLACE(id::text, '-', ''), 1, 5)) "
        "WHERE code IS NULL OR BTRIM(code) = ''"
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_products_code ON products (code)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_code")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS default_price_cents")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS code")
