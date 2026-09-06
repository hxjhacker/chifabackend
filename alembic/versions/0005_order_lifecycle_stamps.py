"""Add order lifecycle timestamps."""

from typing import Sequence, Union

from alembic import op

revision: str = "0005_order_lifecycle_stamps"
down_revision: Union[str, None] = "0004_order_confirm_details"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS confirmed_at timestamptz")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipped_at timestamptz")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivered_at timestamptz")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS cancelled_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS cancelled_at")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS delivered_at")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS shipped_at")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS confirmed_at")
