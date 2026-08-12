"""discovery command receipts

Revision ID: d302b1f4ac09
Revises: c61f4a0d91be
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d302b1f4ac09"
down_revision: str | None = "c61f4a0d91be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_discovery_commands",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", "idempotency_key", name="uq_candidate_discovery_key"),
    )
    op.create_index(
        "ix_candidate_discovery_commands_candidate_id",
        "candidate_discovery_commands",
        ["candidate_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_candidate_discovery_commands_candidate_id",
        table_name="candidate_discovery_commands",
    )
    op.drop_table("candidate_discovery_commands")
