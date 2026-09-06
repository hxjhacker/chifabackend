"""Store Meta Livraison tracking on orders."""

from typing import Sequence, Union

from alembic import op

revision: str = "0006_meta_livraison"
down_revision: Union[str, None] = "0005_order_lifecycle_stamps"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS meta_livraison_code varchar(80)")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS meta_livraison_sent_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS meta_livraison_sent_at")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS meta_livraison_code")
