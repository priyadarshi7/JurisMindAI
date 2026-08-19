"""Portable column types shared by the ORM models.

Production runs on PostgreSQL; unit tests exercise the same model
definitions against an in-memory SQLite database so the ORM layer can be
verified without a live container (no Docker daemon required for the unit
suite). These types pick the PostgreSQL-native representation in production
and a portable equivalent everywhere else, rather than forking the model
definitions per dialect.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CHAR
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import Dialect
from sqlalchemy.types import JSON, TypeDecorator

# JSON column: JSONB on Postgres (indexable, queryable), plain JSON elsewhere.
PortableJSON = JSON().with_variant(JSONB(), "postgresql")


class GUID(TypeDecorator[uuid.UUID]):
    """Platform-independent UUID.

    Uses PostgreSQL's native UUID type in production; stores as a 36-char
    string everywhere else (SQLite, for the unit-test suite).
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return str(value)
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        return str(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)
