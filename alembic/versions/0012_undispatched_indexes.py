"""Indexes for undispatched-order reminder queries."""

from typing import Sequence, Union

from alembic import op

revision: str = "0012_undispatched_indexes"
down_revision: Union[str, None] = "0011_product_sku"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_orders_created_at ON orders (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_orders_confirmed_at ON orders (confirmed_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_orders_meta_livraison_code ON orders (meta_livraison_code)")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_orders_undispatched_status_created
        ON orders (status, created_at DESC)
        WHERE COALESCE(BTRIM(meta_livraison_code), '') = ''
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_orders_undispatched_confirmed
        ON orders (confirmed_at)
        WHERE COALESCE(BTRIM(meta_livraison_code), '') = ''
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_orders_undispatched_confirmed")
    op.execute("DROP INDEX IF EXISTS ix_orders_undispatched_status_created")
    op.execute("DROP INDEX IF EXISTS ix_orders_meta_livraison_code")
    op.execute("DROP INDEX IF EXISTS ix_orders_confirmed_at")
    op.execute("DROP INDEX IF EXISTS ix_orders_created_at")
