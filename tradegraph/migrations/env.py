"""Alembic environment.

Reads the database URL from application settings (`src.core.config`), never
from `alembic.ini`, so the connection string follows the same
managed-secret-only rule as every other credential (docs/11, docs/12 §12).
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.core.config import get_settings
from src.models.orm import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """`Settings.database_url` is the application's async URL
    (`postgresql+asyncpg://...` — what FastAPI and the Celery worker use).
    Alembic's migration runner needs a *sync* driver, so the async variant
    is stripped here rather than maintaining two separate connection
    strings in the environment.
    """
    settings = get_settings()
    if settings.database_url is None:
        raise RuntimeError(
            "DATABASE_URL is not set — see .env.example. Migrations require "
            "a real connection string in the environment, never a default."
        )
    return str(settings.database_url).replace("+asyncpg", "+psycopg")


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
