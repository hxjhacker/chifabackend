"""Add delivery address on orders."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_order_address"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("address", sa.String(length=240), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "address")
