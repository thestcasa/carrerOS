"""add candidate deletion tombstone and database writer fences

Revision ID: d1a7e6c9420b
Revises: c8f320d09a1e
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1a7e6c9420b"
down_revision: str | None = "c8f320d09a1e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FENCED_TABLES = (
    "administrative_audit_records",
    "administrative_command_receipts",
    "candidate_discovery_commands",
    "candidate_discovery_sources",
    "candidate_settings",
    "workflow_tasks",
    "candidate_discovery_runs",
    "candidate_discovery_source_commands",
    "candidate_job_commands",
    "candidate_job_decisions",
    "candidate_job_scores",
    "applications",
    "agent_reviews",
    "application_answers",
    "application_artifacts",
    "application_documents",
    "application_events",
    "browser_sessions",
    "candidate_snapshot_records",
    "correspondence_records",
    "interviews",
    "notifications",
    "offers",
    "security_events",
    "submission_authorizations",
    "human_actions",
)


def upgrade() -> None:
    op.add_column(
        "candidate_settings",
        sa.Column(
            "browser_session_retention_days",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
    )
    op.create_table(
        "administrative_command_receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_id",
            "idempotency_key_sha256",
            name="uq_admin_command_receipt_key",
        ),
    )
    op.create_index(
        op.f("ix_administrative_command_receipts_candidate_id"),
        "administrative_command_receipts",
        ["candidate_id"],
        unique=False,
    )
    op.create_table(
        "candidate_deletion_records",
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("deleted_rows", sa.JSON(), nullable=False),
        sa.Column("deleted_paths", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("candidate_id"),
        sa.UniqueConstraint("idempotency_key_sha256"),
    )
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE FUNCTION careeros_reject_deleted_candidate_write()
            RETURNS trigger AS $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM candidate_deletion_records
                    WHERE candidate_id = NEW.candidate_id
                ) THEN
                    RAISE EXCEPTION 'candidate is deleted'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        for table in _FENCED_TABLES:
            op.execute(
                f"""
                CREATE CONSTRAINT TRIGGER trg_{table}_candidate_not_deleted
                AFTER INSERT OR UPDATE ON {table}
                DEFERRABLE INITIALLY DEFERRED
                FOR EACH ROW EXECUTE FUNCTION careeros_reject_deleted_candidate_write()
                """
            )
    elif dialect == "sqlite":
        for table in _FENCED_TABLES:
            for operation in ("INSERT", "UPDATE"):
                suffix = operation.casefold()
                op.execute(
                    f"""
                    CREATE TRIGGER trg_{table}_candidate_not_deleted_{suffix}
                    BEFORE {operation} ON {table}
                    FOR EACH ROW
                    WHEN EXISTS (
                        SELECT 1 FROM candidate_deletion_records
                        WHERE candidate_id = NEW.candidate_id
                    )
                    BEGIN
                        SELECT RAISE(ABORT, 'candidate is deleted');
                    END
                    """
                )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table in _FENCED_TABLES:
            op.execute(f"DROP TRIGGER trg_{table}_candidate_not_deleted ON {table}")
        op.execute("DROP FUNCTION careeros_reject_deleted_candidate_write()")
    elif dialect == "sqlite":
        for table in _FENCED_TABLES:
            for operation in ("insert", "update"):
                op.execute(f"DROP TRIGGER trg_{table}_candidate_not_deleted_{operation}")
    op.drop_table("candidate_deletion_records")
    op.drop_table("administrative_command_receipts")
    op.drop_column("candidate_settings", "browser_session_retention_days")
