"""Quick warehouse product category + stock quantity."""

from typing import Sequence, Union

from alembic import op

revision: str = "0015_product_catalog_reorg"
down_revision: Union[str, None] = "0014_quick_product_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS category varchar(32) DEFAULT 'standard' NOT NULL")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS is_quick_stock boolean DEFAULT false NOT NULL")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS stock_quantity integer DEFAULT 0 NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_category ON products (category)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_is_quick_stock ON products (is_quick_stock)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_is_quick_stock")
    op.execute("DROP INDEX IF EXISTS ix_products_category")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS stock_quantity")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS is_quick_stock")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS category")
