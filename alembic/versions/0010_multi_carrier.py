"""Multi-carrier shipping: order.carrier and city_tarifs.quick_district_id."""

from typing import Sequence, Union

from alembic import op

revision: str = "0010_multi_carrier"
down_revision: Union[str, None] = "0009_city_tarifs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS carrier varchar(50) DEFAULT 'meta_livraison' NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_orders_carrier ON orders (carrier)")
    op.execute("ALTER TABLE city_tarifs ADD COLUMN IF NOT EXISTS quick_district_id integer")
    op.execute("CREATE INDEX IF NOT EXISTS ix_city_tarifs_quick_district_id ON city_tarifs (quick_district_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_city_tarifs_quick_district_id")
    op.execute("ALTER TABLE city_tarifs DROP COLUMN IF EXISTS quick_district_id")
    op.execute("DROP INDEX IF EXISTS ix_orders_carrier")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS carrier")
