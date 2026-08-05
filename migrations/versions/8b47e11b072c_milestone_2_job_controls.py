"""milestone 2 candidate job controls

Revision ID: 8b47e11b072c
Revises: 5d91d7e52a21
Create Date: 2026-08-04 23:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8b47e11b072c"
down_revision: str | None = "5d91d7e52a21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_job_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("verified_open_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["global_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", "job_id", name="uq_candidate_job_decision"),
    )
    op.create_index(
        "ix_candidate_job_decisions_candidate_id", "candidate_job_decisions", ["candidate_id"]
    )
    op.create_table(
        "candidate_job_commands",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("command", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["global_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", "idempotency_key", name="uq_candidate_job_command"),
    )
    op.create_index(
        "ix_candidate_job_commands_candidate_id", "candidate_job_commands", ["candidate_id"]
    )
    op.create_index("ix_candidate_job_decisions_job_id", "candidate_job_decisions", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_candidate_job_commands_candidate_id", table_name="candidate_job_commands")
    op.drop_table("candidate_job_commands")
    op.drop_index("ix_candidate_job_decisions_job_id", table_name="candidate_job_decisions")
    op.drop_index("ix_candidate_job_decisions_candidate_id", table_name="candidate_job_decisions")
    op.drop_table("candidate_job_decisions")
