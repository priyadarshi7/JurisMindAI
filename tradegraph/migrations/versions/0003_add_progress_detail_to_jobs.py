"""Add jobs.progress_detail — a human-readable "what's happening right now"
string the worker commits as each pipeline stage starts (docs/16 Phase 1
Application: real progress streaming instead of an opaque "running" for the
whole multi-minute run).

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("progress_detail", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "progress_detail")
