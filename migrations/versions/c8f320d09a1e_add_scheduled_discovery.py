"""add candidate-owned scheduled discovery sources and runs

Revision ID: c8f320d09a1e
Revises: b4e1f59c2d73
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8f320d09a1e"
down_revision: str | None = "b4e1f59c2d73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_discovery_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=False),
        sa.Column("company_domain", sa.String(length=255), nullable=False),
        sa.Column("board_token", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("cadence_minutes", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_id", "provider", "board_token", name="uq_candidate_discovery_source"
        ),
        sa.UniqueConstraint(
            "candidate_id", "idempotency_key", name="uq_candidate_discovery_source_command"
        ),
        sa.UniqueConstraint("candidate_id", "id", name="uq_candidate_discovery_source_scope"),
    )
    op.create_index(
        op.f("ix_candidate_discovery_sources_candidate_id"),
        "candidate_discovery_sources",
        ["candidate_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_discovery_sources_next_run_at"),
        "candidate_discovery_sources",
        ["next_run_at"],
        unique=False,
    )
    op.create_table(
        "candidate_discovery_source_commands",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id", "source_id"],
            ["candidate_discovery_sources.candidate_id", "candidate_discovery_sources.id"],
            name="fk_discovery_source_command_scope",
        ),
        sa.ForeignKeyConstraint(["source_id"], ["candidate_discovery_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_id", "idempotency_key", name="uq_candidate_discovery_source_update_key"
        ),
    )
    op.create_index(
        op.f("ix_candidate_discovery_source_commands_candidate_id"),
        "candidate_discovery_source_commands",
        ["candidate_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_discovery_source_commands_source_id"),
        "candidate_discovery_source_commands",
        ["source_id"],
        unique=False,
    )
    op.create_table(
        "candidate_discovery_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("cadence_bucket", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("discovered_count", sa.Integer(), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("lease_attempt", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id", "source_id"],
            ["candidate_discovery_sources.candidate_id", "candidate_discovery_sources.id"],
            name="fk_discovery_run_source_scope",
        ),
        sa.ForeignKeyConstraint(["source_id"], ["candidate_discovery_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "cadence_bucket", name="uq_discovery_run_bucket"),
    )
    op.create_index(
        op.f("ix_candidate_discovery_runs_candidate_id"),
        "candidate_discovery_runs",
        ["candidate_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_discovery_runs_source_id"),
        "candidate_discovery_runs",
        ["source_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_candidate_discovery_runs_source_id"),
        table_name="candidate_discovery_runs",
    )
    op.drop_index(
        op.f("ix_candidate_discovery_runs_candidate_id"),
        table_name="candidate_discovery_runs",
    )
    op.drop_table("candidate_discovery_runs")
    op.drop_index(
        op.f("ix_candidate_discovery_source_commands_source_id"),
        table_name="candidate_discovery_source_commands",
    )
    op.drop_index(
        op.f("ix_candidate_discovery_source_commands_candidate_id"),
        table_name="candidate_discovery_source_commands",
    )
    op.drop_table("candidate_discovery_source_commands")
    op.drop_index(
        op.f("ix_candidate_discovery_sources_next_run_at"),
        table_name="candidate_discovery_sources",
    )
    op.drop_index(
        op.f("ix_candidate_discovery_sources_candidate_id"),
        table_name="candidate_discovery_sources",
    )
    op.drop_table("candidate_discovery_sources")
