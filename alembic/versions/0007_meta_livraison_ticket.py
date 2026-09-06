"""Store Meta Livraison ticket / label URL on orders."""

from typing import Sequence, Union

from alembic import op

revision: str = "0007_meta_livraison_ticket"
down_revision: Union[str, None] = "0006_meta_livraison"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS meta_livraison_ticket_url text")


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS meta_livraison_ticket_url")
