"""Async SQLAlchemy engine/session factory for PostgreSQL — the system of
record (docs/01 Tier 3).

Separate from `migrations/env.py`, which manages schema evolution with its
own synchronous engine — this module is for application/worker runtime
queries only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    if settings.database_url is None:
        raise RuntimeError(
            "DATABASE_URL is not set — see .env.example. The application "
            "must not silently fall back to a default connection string."
        )
    return create_async_engine(str(settings.database_url), pool_pre_ping=True)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency — one session per request, always closed."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session
