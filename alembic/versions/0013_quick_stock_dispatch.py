"""Carrier status + dispatched_at for Quick stock dispatch."""

from typing import Sequence, Union

from alembic import op

revision: str = "0013_quick_stock_dispatch"
down_revision: Union[str, None] = "0012_undispatched_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS carrier_status varchar(50)")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS dispatched_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS dispatched_at")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS carrier_status")
