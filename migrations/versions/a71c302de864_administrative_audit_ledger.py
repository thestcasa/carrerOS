"""administrative audit ledger

Revision ID: a71c302de864
Revises: f9a14d72c530
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a71c302de864"
down_revision: str | None = "f9a14d72c530"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "administrative_audit_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("previous_hash", sa.String(length=64), nullable=True),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_hash"),
    )
    op.create_index(
        "ix_administrative_audit_records_candidate_id",
        "administrative_audit_records",
        ["candidate_id"],
    )
    op.create_index(
        "ix_administrative_audit_records_event_type",
        "administrative_audit_records",
        ["event_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_administrative_audit_records_event_type",
        table_name="administrative_audit_records",
    )
    op.drop_index(
        "ix_administrative_audit_records_candidate_id",
        table_name="administrative_audit_records",
    )
    op.drop_table("administrative_audit_records")
