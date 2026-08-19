"""Integration test: run the real Alembic migration against a live
PostgreSQL instance and confirm it exactly matches the ORM models.

Requires `docker compose up -d postgres` and a `.env` with a working
DATABASE_URL — this is precisely the docs/12 CI integration-test stage.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext

from src.core.config import get_settings
from src.models.orm import Base

REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_TABLES = {
    "tenants",
    "users",
    "documents",
    "chunks",
    "legal_sections",
    "jobs",
    "evidence_items",
    "claims",
    "claim_evidence",
    "citations",
    "reports",
    "audits",
    "ingestion_runs",
}


def _alembic_config() -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return cfg


@pytest.fixture
def database_available() -> None:
    settings = get_settings()
    if settings.database_url is None:
        pytest.skip("DATABASE_URL not set — see .env.example")
    engine = sa.create_engine(str(settings.database_url).replace("+asyncpg", "+psycopg"))
    try:
        with engine.connect():
            pass
    except Exception as exc:
        pytest.skip(f"PostgreSQL not reachable: {exc}")
    finally:
        engine.dispose()


def test_migration_matches_orm_models_exactly(database_available: None) -> None:
    """The real `alembic check` — run programmatically so a future edit to
    either the migration or the ORM models that drifts from the other fails
    the test suite, not just a manual command someone forgot to run.
    """
    settings = get_settings()
    sync_url = str(settings.database_url).replace("+asyncpg", "+psycopg")
    engine = sa.create_engine(sync_url)

    cfg = _alembic_config()
    try:
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")

        with engine.connect() as conn:
            migration_ctx = MigrationContext.configure(conn)
            diff = compare_metadata(migration_ctx, Base.metadata)

        assert diff == [], f"migration and ORM models have drifted: {diff}"

        with engine.connect() as conn:
            tables = set(sa.inspect(conn).get_table_names())
        assert EXPECTED_TABLES.issubset(tables)
    finally:
        # Always leave the schema at head, not base: this is a shared dev
        # database other integration tests in the same pytest session
        # depend on having tables present. Downgrading to base here as
        # "cleanup" previously broke sibling tests whenever this file
        # happened to run before them (file collection order is not
        # guaranteed alphabetical).
        command.upgrade(cfg, "head")
        engine.dispose()
