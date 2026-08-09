"""add evidence-backed autonomy acceptance records

Revision ID: 6a9d4e2f7b10
Revises: 2a4d7e9f1b30
Create Date: 2026-08-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6a9d4e2f7b10"
down_revision: str | None = "2a4d7e9f1b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _install_candidate_fence() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE CONSTRAINT TRIGGER trg_ats_adapter_acceptance_records_candidate_not_deleted
            AFTER INSERT OR UPDATE ON ats_adapter_acceptance_records
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION careeros_reject_deleted_candidate_write()
            """
        )
    elif dialect == "sqlite":
        for operation in ("INSERT", "UPDATE"):
            suffix = operation.casefold()
            op.execute(
                f"""
                CREATE TRIGGER trg_ats_adapter_acceptance_records_candidate_not_deleted_{suffix}
                BEFORE {operation} ON ats_adapter_acceptance_records
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


def _install_immutable_update_fence() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE FUNCTION careeros_reject_ats_acceptance_update()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'ATS adapter acceptance records are immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_ats_adapter_acceptance_records_immutable
            BEFORE UPDATE ON ats_adapter_acceptance_records
            FOR EACH ROW EXECUTE FUNCTION careeros_reject_ats_acceptance_update()
            """
        )
    elif dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER trg_ats_adapter_acceptance_records_immutable
            BEFORE UPDATE ON ats_adapter_acceptance_records
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'ATS adapter acceptance records are immutable');
            END
            """
        )


def upgrade() -> None:
    op.add_column(
        "candidate_settings",
        sa.Column("autonomy_confirmation_scope_sha256", sa.String(length=64)),
    )
    op.add_column(
        "candidate_settings",
        sa.Column("autonomy_confirmed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "ats_adapter_acceptance_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("adapter", sa.String(length=32), nullable=False),
        sa.Column("adapter_version", sa.String(length=64), nullable=False),
        sa.Column("destination_policy_sha256", sa.String(length=64), nullable=False),
        sa.Column("form_pattern", sa.String(length=64), nullable=False),
        sa.Column("form_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("package_sha256", sa.String(length=64), nullable=False),
        sa.Column("browser_task_id", sa.Uuid(), nullable=False),
        sa.Column("browser_attempt", sa.Integer(), nullable=False),
        sa.Column("evidence_manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.CheckConstraint("browser_attempt >= 1", name="ck_ats_adapter_acceptance_attempt"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_ats_adapter_acceptance_application_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_id",
            "adapter",
            "adapter_version",
            "form_fingerprint",
            "browser_task_id",
            "browser_attempt",
            name="uq_ats_adapter_acceptance_evidence",
        ),
    )
    op.create_index(
        op.f("ix_ats_adapter_acceptance_records_application_id"),
        "ats_adapter_acceptance_records",
        ["application_id"],
    )
    op.create_index(
        op.f("ix_ats_adapter_acceptance_records_adapter"),
        "ats_adapter_acceptance_records",
        ["adapter"],
    )
    op.create_index(
        op.f("ix_ats_adapter_acceptance_records_candidate_id"),
        "ats_adapter_acceptance_records",
        ["candidate_id"],
    )
    _install_candidate_fence()
    _install_immutable_update_fence()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            "DROP TRIGGER trg_ats_adapter_acceptance_records_immutable "
            "ON ats_adapter_acceptance_records"
        )
        op.execute("DROP FUNCTION careeros_reject_ats_acceptance_update()")
        op.execute(
            "DROP TRIGGER trg_ats_adapter_acceptance_records_candidate_not_deleted "
            "ON ats_adapter_acceptance_records"
        )
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER trg_ats_adapter_acceptance_records_immutable")
        for operation in ("insert", "update"):
            op.execute(
                f"DROP TRIGGER trg_ats_adapter_acceptance_records_candidate_not_deleted_{operation}"
            )
    op.drop_index(
        op.f("ix_ats_adapter_acceptance_records_candidate_id"),
        table_name="ats_adapter_acceptance_records",
    )
    op.drop_index(
        op.f("ix_ats_adapter_acceptance_records_adapter"),
        table_name="ats_adapter_acceptance_records",
    )
    op.drop_index(
        op.f("ix_ats_adapter_acceptance_records_application_id"),
        table_name="ats_adapter_acceptance_records",
    )
    op.drop_table("ats_adapter_acceptance_records")
    op.drop_column("candidate_settings", "autonomy_confirmed_at")
    op.drop_column("candidate_settings", "autonomy_confirmation_scope_sha256")
