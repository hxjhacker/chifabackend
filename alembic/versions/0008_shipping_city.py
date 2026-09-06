"""Official Meta Livraison destination city selected by admin."""

from typing import Sequence, Union

from alembic import op

revision: str = "0008_shipping_city"
down_revision: Union[str, None] = "0007_meta_livraison_ticket"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_city varchar(160)")


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS shipping_city")
