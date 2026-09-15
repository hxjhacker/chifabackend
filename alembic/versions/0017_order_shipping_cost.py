"""Persist the carrier shipping fee on each order."""

from typing import Sequence, Union

from alembic import op

revision: str = "0017_order_shipping_cost"
down_revision: Union[str, None] = "0016_delivery_cities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_cost double precision")


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS shipping_cost")
