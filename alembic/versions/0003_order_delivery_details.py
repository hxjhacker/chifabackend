"""Add courier delivery details on orders."""

from typing import Sequence, Union

from alembic import op

revision: str = "0003_order_delivery_details"
down_revision: Union[str, None] = "0002_order_address"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS address text")
    op.execute("ALTER TABLE orders ALTER COLUMN address TYPE text USING address::text")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS quartier varchar(120)")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS street varchar(160)")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS building varchar(80)")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS landmark varchar(160)")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_window varchar(32)")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS courier_notes text")


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS courier_notes")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS delivery_window")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS landmark")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS building")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS street")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS quartier")
    op.execute("ALTER TABLE orders ALTER COLUMN address TYPE varchar(240) USING left(address::text, 240)")
