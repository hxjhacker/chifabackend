"""Quick warehouse product ID on the catalog."""

from typing import Sequence, Union

from alembic import op

revision: str = "0014_quick_product_id"
down_revision: Union[str, None] = "0013_quick_stock_dispatch"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS quick_product_id integer")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_quick_product_id ON products (quick_product_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_quick_product_id")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS quick_product_id")
