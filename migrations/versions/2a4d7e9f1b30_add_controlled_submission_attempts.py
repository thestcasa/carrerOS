"""add controlled submission attempts

Revision ID: 2a4d7e9f1b30
Revises: 7f2c9d1e4a60
Create Date: 2026-08-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2a4d7e9f1b30"
down_revision: str | None = "7f2c9d1e4a60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _install_candidate_fence() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE CONSTRAINT TRIGGER trg_controlled_submission_attempts_candidate_not_deleted
            AFTER INSERT OR UPDATE ON controlled_submission_attempts
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION careeros_reject_deleted_candidate_write()
            """
        )
    elif dialect == "sqlite":
        for operation in ("INSERT", "UPDATE"):
            suffix = operation.casefold()
            op.execute(
                f"""
                CREATE TRIGGER trg_controlled_submission_attempts_candidate_not_deleted_{suffix}
                BEFORE {operation} ON controlled_submission_attempts
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


def _restore_authorization_fence() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    for operation in ("INSERT", "UPDATE"):
        suffix = operation.casefold()
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_submission_authorizations_candidate_not_deleted_{suffix}"
        )
        op.execute(
            f"""
            CREATE TRIGGER trg_submission_authorizations_candidate_not_deleted_{suffix}
            BEFORE {operation} ON submission_authorizations
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


def upgrade() -> None:
    with op.batch_alter_table("submission_authorizations") as batch:
        batch.add_column(
            sa.Column(
                "execution_mode",
                sa.String(length=16),
                nullable=False,
                server_default="synthetic",
            )
        )
        batch.add_column(sa.Column("adapter", sa.String(length=32)))
        batch.add_column(sa.Column("target_url_sha256", sa.String(length=64)))
        batch.add_column(sa.Column("authorized_state_version", sa.Integer()))
        batch.create_check_constraint(
            "ck_submission_authorization_execution_mode",
            "execution_mode IN ('synthetic', 'controlled')",
        )
        batch.create_unique_constraint(
            "uq_submission_authorization_scope",
            ["candidate_id", "application_id", "authorization_id"],
        )
    _restore_authorization_fence()
    op.create_table(
        "controlled_submission_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid()),
        sa.Column("browser_session_id", sa.Uuid(), nullable=False),
        sa.Column("adapter", sa.String(length=32), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("target_origin", sa.String(length=255), nullable=False),
        sa.Column("form_fingerprint", sa.String(length=64)),
        sa.Column("form_payload_sha256", sa.String(length=64)),
        sa.Column("package_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("pre_click_screenshot_sha256", sa.String(length=64)),
        sa.Column("pre_click_page_sha256", sa.String(length=64)),
        sa.Column("click_nonce_sha256", sa.String(length=64)),
        sa.Column("click_boundary_entered_at", sa.DateTime(timezone=True)),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.Column("confirmation_reference", sa.String(length=255)),
        sa.Column("final_evidence_sha256", sa.String(length=64)),
        sa.Column("failure_category", sa.String(length=64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "status IN ('prepared', 'click_authorized', 'confirmed', "
            "'confirmation_missing', 'unknown_after_click', 'denied')",
            name="ck_controlled_submission_status",
        ),
        sa.CheckConstraint(
            "status IN ('prepared', 'denied') OR "
            "(form_fingerprint IS NOT NULL AND form_payload_sha256 IS NOT NULL "
            "AND pre_click_screenshot_sha256 IS NOT NULL "
            "AND pre_click_page_sha256 IS NOT NULL AND click_nonce_sha256 IS NOT NULL "
            "AND click_boundary_entered_at IS NOT NULL)",
            name="ck_controlled_submission_click_evidence",
        ),
        sa.ForeignKeyConstraint(["browser_session_id"], ["browser_sessions.id"]),
        sa.ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_controlled_submission_application_scope",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id", "application_id", "authorization_id"],
            [
                "submission_authorizations.candidate_id",
                "submission_authorizations.application_id",
                "submission_authorizations.authorization_id",
            ],
            name="fk_controlled_submission_authorization_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authorization_id", name="uq_controlled_submission_authorization"),
        sa.UniqueConstraint(
            "candidate_id", "application_id", "id", name="uq_controlled_submission_scope"
        ),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index(
        op.f("ix_controlled_submission_attempts_application_id"),
        "controlled_submission_attempts",
        ["application_id"],
    )
    op.create_index(
        op.f("ix_controlled_submission_attempts_browser_session_id"),
        "controlled_submission_attempts",
        ["browser_session_id"],
    )
    op.create_index(
        op.f("ix_controlled_submission_attempts_authorization_id"),
        "controlled_submission_attempts",
        ["authorization_id"],
    )
    op.create_index(
        op.f("ix_controlled_submission_attempts_candidate_id"),
        "controlled_submission_attempts",
        ["candidate_id"],
    )
    op.create_index(
        "uq_controlled_submission_active_application",
        "controlled_submission_attempts",
        ["candidate_id", "application_id"],
        unique=True,
        sqlite_where=sa.text("status <> 'denied'"),
        postgresql_where=sa.text("status <> 'denied'"),
    )
    _install_candidate_fence()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            "DROP TRIGGER trg_controlled_submission_attempts_candidate_not_deleted "
            "ON controlled_submission_attempts"
        )
    elif dialect == "sqlite":
        for operation in ("insert", "update"):
            op.execute(
                f"DROP TRIGGER IF EXISTS "
                f"trg_controlled_submission_attempts_candidate_not_deleted_{operation}"
            )
    op.drop_table("controlled_submission_attempts")
    with op.batch_alter_table("submission_authorizations") as batch:
        batch.drop_constraint("uq_submission_authorization_scope", type_="unique")
        batch.drop_constraint("ck_submission_authorization_execution_mode", type_="check")
        batch.drop_column("authorized_state_version")
        batch.drop_column("target_url_sha256")
        batch.drop_column("adapter")
        batch.drop_column("execution_mode")
    _restore_authorization_fence()
