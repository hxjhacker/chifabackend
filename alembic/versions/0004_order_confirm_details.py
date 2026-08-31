"""Add region, bundle, and secondary qty on orders."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_order_confirm_details"
down_revision: Union[str, None] = "0003_order_delivery_details"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("orders", "address", existing_type=sa.String(length=500), type_=sa.Text())
    op.add_column("orders", sa.Column("region_id", sa.String(length=8), nullable=True))
    op.add_column("orders", sa.Column("bundle_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("orders", sa.Column("secondary_qty", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    op.drop_column("orders", "secondary_qty")
    op.drop_column("orders", "bundle_enabled")
    op.drop_column("orders", "region_id")
    op.alter_column("orders", "address", existing_type=sa.Text(), type_=sa.String(length=500))
