"""Add region, bundle, and secondary qty on orders."""

from typing import Sequence, Union

from alembic import op

revision: str = "0004_order_confirm_details"
down_revision: Union[str, None] = "0003_order_delivery_details"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS address text")
    op.execute("ALTER TABLE orders ALTER COLUMN address TYPE text USING address::text")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS region_id varchar(32)")
    op.execute("ALTER TABLE orders ALTER COLUMN region_id TYPE varchar(32)")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS bundle_enabled boolean DEFAULT false")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS secondary_qty integer DEFAULT 1")


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS secondary_qty")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS bundle_enabled")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS region_id")
    op.execute("ALTER TABLE orders ALTER COLUMN address TYPE varchar(500) USING address::varchar(500)")
