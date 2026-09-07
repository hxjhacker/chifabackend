"""Alembic env — URL comes from app.config (Easypanel DATABASE_URL)."""

from logging.config import fileConfig

from alembic import context
from sqlmodel import SQLModel

from app.config import settings
from app.models import CityTarif, Order, OrderItem, Product, TrackingEvent as TrackingEvent  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.sqlalchemy_url.replace("%", "%%"))
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    url = settings.sqlalchemy_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import create_engine

    connectable = create_engine(settings.sqlalchemy_url, pool_pre_ping=True)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
