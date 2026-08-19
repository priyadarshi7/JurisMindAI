"""Add jobs.error_message — set only on JobStatus.FAILED, distinct from the
truthful `insufficient_evidence` answer (docs/16 Phase 1 Application work:
the /jobs API needs somewhere to surface a worker crash to the caller).

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("error_message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "error_message")
