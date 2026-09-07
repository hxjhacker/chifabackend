"""Official Meta Livraison city tariffs (FES origin)."""

from typing import Sequence, Union

from alembic import op

revision: str = "0009_city_tarifs"
down_revision: Union[str, None] = "0008_shipping_city"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS city_tarifs (
          id uuid PRIMARY KEY,
          meta_city_id varchar(32) NOT NULL,
          city_name varchar(160) NOT NULL,
          delivery_fee double precision NOT NULL DEFAULT 35,
          refusal_fee double precision NOT NULL DEFAULT 10,
          return_fee double precision NOT NULL DEFAULT 0,
          hub_name varchar(120),
          updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_city_tarifs_meta_city_id ON city_tarifs (meta_city_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_city_tarifs_city_name ON city_tarifs (city_name)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS city_tarifs")
