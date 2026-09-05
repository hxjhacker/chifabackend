"""Store Meta Livraison tracking on orders."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_meta_livraison"
down_revision: Union[str, None] = "0005_order_lifecycle_stamps"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("meta_livraison_code", sa.String(length=80), nullable=True))
    op.add_column("orders", sa.Column("meta_livraison_sent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "meta_livraison_sent_at")
    op.drop_column("orders", "meta_livraison_code")
