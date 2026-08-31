"""Add courier delivery details on orders."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_order_delivery_details"
down_revision: Union[str, None] = "0002_order_address"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("orders", "address", existing_type=sa.String(length=240), type_=sa.String(length=500))
    op.add_column("orders", sa.Column("quartier", sa.String(length=120), nullable=True))
    op.add_column("orders", sa.Column("street", sa.String(length=160), nullable=True))
    op.add_column("orders", sa.Column("building", sa.String(length=80), nullable=True))
    op.add_column("orders", sa.Column("landmark", sa.String(length=160), nullable=True))
    op.add_column("orders", sa.Column("delivery_window", sa.String(length=32), nullable=True))
    op.add_column("orders", sa.Column("courier_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "courier_notes")
    op.drop_column("orders", "delivery_window")
    op.drop_column("orders", "landmark")
    op.drop_column("orders", "building")
    op.drop_column("orders", "street")
    op.drop_column("orders", "quartier")
    op.alter_column("orders", "address", existing_type=sa.String(length=500), type_=sa.String(length=240))
