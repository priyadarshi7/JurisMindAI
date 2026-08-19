"""Legal corpus foundations (NyayaGraph pivot, docs/16 Phase 1 Foundations).

Adds nullable legal-specific columns to `documents`, and creates
`legal_sections` (first-class identity for a Constitution article / Act
section, distinct from a generic chunk — see src/models/orm.py::LegalSection
docstring for why).

❗ `document_type` needs no DDL change here despite gaining five new
StrEnum values (`constitution`, `central_act`, `judgment_sc`, `judgment_hc`,
`notification`) — verified live against a real PostgreSQL instance
(2026-08-19) that 0001's hand-written `op.create_table("documents", ...)`
never actually materialized a CHECK constraint for this column: `\\d
documents` shows a plain `character varying(21)` with zero CHECK
constraints, even though `src/models/orm.py`'s `Enum(DocumentType,
native_enum=False)` nominally implies one. `op.create_table` builds an
ad-hoc `Table` and emits `CREATE TABLE` directly — it never fires the
column-to-table `_set_table` event a full `MetaData.create_all()` would,
which is what actually attaches the non-native-Enum's CheckConstraint. This
was already true before this migration (`test_migration.py`'s
`compare_metadata` diff, which does not check CHECK-constraint bodies by
default, never caught it) — enum validity is enforced at the
Python/Pydantic layer only. Widening the Python enum needs no matching SQL;
all five new values are well under the existing VARCHAR(21) width.

Hand-written, mirroring 0001's own admission: verify with the real
`tests/integration/test_migration.py` (`alembic check`-equivalent) against
a live database before this ships, and treat any diff it reports as a bug
in this file, not in the ORM models.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from src.models.db_types import GUID

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("court", sa.String(128), nullable=True))
    op.add_column("documents", sa.Column("case_citation", sa.String(255), nullable=True))
    op.add_column("documents", sa.Column("act_code", sa.String(64), nullable=True))
    op.add_column("documents", sa.Column("authority_tier", sa.Integer(), nullable=True))
    op.create_index("ix_documents_act_code", "documents", ["act_code"])

    op.create_table(
        "legal_sections",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("document_id", GUID(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("chunk_id", GUID(), sa.ForeignKey("chunks.id"), nullable=True),
        sa.Column("section_number", sa.String(32), nullable=False),
        sa.Column("section_title", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_legal_sections_document_id", "legal_sections", ["document_id"])
    op.create_unique_constraint(
        "uq_legal_sections_document_number",
        "legal_sections",
        ["document_id", "section_number"],
    )


def downgrade() -> None:
    op.drop_table("legal_sections")

    op.drop_index("ix_documents_act_code", table_name="documents")
    op.drop_column("documents", "authority_tier")
    op.drop_column("documents", "act_code")
    op.drop_column("documents", "case_citation")
    op.drop_column("documents", "court")
