"""tenant-bound relationships and durable submission authorizations

Revision ID: c61f4a0d91be
Revises: 8b47e11b072c
Create Date: 2026-08-05 20:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c61f4a0d91be"
down_revision: str | None = "8b47e11b072c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


APPLICATION_STATE = sa.Enum(
    "DISCOVERED",
    "NORMALIZED",
    "SECURITY_CHECK",
    "CLASSIFIED",
    "SCORED",
    "SKIPPED",
    "SHORTLISTED",
    "CANDIDATE_SNAPSHOT_CREATED",
    "MATERIALS_GENERATING",
    "MATERIALS_READY",
    "REVIEW_PENDING",
    "REVIEW_FAILED",
    "APPLICATION_STARTED",
    "FORM_FILLING",
    "HUMAN_ACTION_REQUIRED",
    "FINAL_VALIDATION",
    "READY_TO_SUBMIT",
    "SUBMITTING",
    "SUBMITTED",
    "CONFIRMED",
    "FAILED_RETRYABLE",
    "FAILED_FINAL",
    "CLOSED",
    "REJECTED",
    "INTERVIEW",
    "OFFER",
    "WITHDRAWN",
    name="applicationstate",
    native_enum=False,
)


def _application_child_scope(table_name: str, constraint_name: str) -> None:
    with op.batch_alter_table(table_name) as batch:
        batch.create_foreign_key(
            constraint_name,
            "applications",
            ["candidate_id", "application_id"],
            ["candidate_id", "id"],
        )


def upgrade() -> None:
    with op.batch_alter_table("candidate_job_scores") as batch:
        batch.create_unique_constraint(
            "uq_candidate_job_score_scope", ["candidate_id", "job_id", "id"]
        )
    with op.batch_alter_table("applications") as batch:
        batch.add_column(
            sa.Column("state_version", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(sa.Column("archive_uri", sa.Text(), nullable=True))
        batch.add_column(sa.Column("confirmation_reference", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_unique_constraint("uq_application_scope", ["candidate_id", "id"])
        batch.create_foreign_key(
            "fk_application_candidate_score",
            "candidate_job_scores",
            ["candidate_id", "job_id", "score_id"],
            ["candidate_id", "job_id", "id"],
        )

    for table_name, constraint_name in (
        ("application_documents", "fk_application_document_scope"),
        ("application_answers", "fk_application_answer_scope"),
        ("application_events", "fk_application_event_scope"),
        ("security_events", "fk_security_event_application_scope"),
        ("browser_sessions", "fk_browser_session_scope"),
        ("human_actions", "fk_human_action_scope"),
        ("interviews", "fk_interview_scope"),
        ("offers", "fk_offer_scope"),
        ("agent_reviews", "fk_agent_review_scope"),
    ):
        _application_child_scope(table_name, constraint_name)

    with op.batch_alter_table("human_actions") as batch:
        batch.add_column(sa.Column("kind", sa.String(length=64), nullable=True))
        batch.add_column(
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending")
        )
        batch.add_column(sa.Column("browser_session_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("screenshot_uri", sa.Text(), nullable=True))
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_human_action_browser_session",
            "browser_sessions",
            ["browser_session_id"],
            ["id"],
        )

    op.create_table(
        "submission_authorizations",
        sa.Column("authorization_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_state", APPLICATION_STATE, nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_submission_authorization_scope",
        ),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.PrimaryKeyConstraint("authorization_id"),
    )
    op.create_index(
        "ix_submission_authorizations_application_id",
        "submission_authorizations",
        ["application_id"],
    )
    op.create_index(
        "ix_submission_authorizations_candidate_id",
        "submission_authorizations",
        ["candidate_id"],
    )

    op.create_table(
        "candidate_snapshot_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("profile_version", sa.String(length=32), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_candidate_snapshot_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_id", "application_id", "profile_version", name="uq_snapshot_profile"
        ),
    )
    op.create_index(
        "ix_candidate_snapshot_records_application_id",
        "candidate_snapshot_records",
        ["application_id"],
    )
    op.create_index(
        "ix_candidate_snapshot_records_candidate_id",
        "candidate_snapshot_records",
        ["candidate_id"],
    )
    op.create_table(
        "application_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("immutable", sa.Boolean(), nullable=False),
        sa.Column("artifact_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_application_artifact_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_id", "application_id", "kind", "version", name="uq_application_artifact"
        ),
    )
    op.create_index(
        "ix_application_artifacts_application_id",
        "application_artifacts",
        ["application_id"],
    )
    op.create_index(
        "ix_application_artifacts_candidate_id",
        "application_artifacts",
        ["candidate_id"],
    )
    op.create_table(
        "candidate_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("automation_mode", sa.String(length=32), nullable=False),
        sa.Column("discovery_enabled", sa.Boolean(), nullable=False),
        sa.Column("emergency_stopped", sa.Boolean(), nullable=False),
        sa.Column("allowed_ats_adapters", sa.JSON(), nullable=False),
        sa.Column("tested_ats_adapters", sa.JSON(), nullable=False),
        sa.Column("dry_run_acceptance_passed", sa.Boolean(), nullable=False),
        sa.Column("explicit_autonomy_confirmation", sa.Boolean(), nullable=False),
        sa.Column("maximum_applications_per_day", sa.Integer(), nullable=False),
        sa.Column("maximum_applications_per_week", sa.Integer(), nullable=False),
        sa.Column("maximum_applications_per_company_30_days", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", name="uq_candidate_settings"),
    )
    op.create_index("ix_candidate_settings_candidate_id", "candidate_settings", ["candidate_id"])
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("immediate", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_notification_application_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_application_id", "notifications", ["application_id"])
    op.create_index("ix_notifications_candidate_id", "notifications", ["candidate_id"])
    op.create_table(
        "correspondence_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("external_message_id", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("sender", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("body_sha256", sa.String(length=64), nullable=False),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_correspondence_application_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_id", "external_message_id", name="uq_correspondence_external_message"
        ),
    )
    op.create_index(
        "ix_correspondence_records_application_id",
        "correspondence_records",
        ["application_id"],
    )
    op.create_index(
        "ix_correspondence_records_candidate_id",
        "correspondence_records",
        ["candidate_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_correspondence_records_candidate_id", table_name="correspondence_records")
    op.drop_index("ix_correspondence_records_application_id", table_name="correspondence_records")
    op.drop_table("correspondence_records")
    op.drop_index("ix_notifications_candidate_id", table_name="notifications")
    op.drop_index("ix_notifications_application_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_candidate_settings_candidate_id", table_name="candidate_settings")
    op.drop_table("candidate_settings")
    op.drop_index("ix_application_artifacts_candidate_id", table_name="application_artifacts")
    op.drop_index("ix_application_artifacts_application_id", table_name="application_artifacts")
    op.drop_table("application_artifacts")
    op.drop_index(
        "ix_candidate_snapshot_records_candidate_id", table_name="candidate_snapshot_records"
    )
    op.drop_index(
        "ix_candidate_snapshot_records_application_id", table_name="candidate_snapshot_records"
    )
    op.drop_table("candidate_snapshot_records")
    op.drop_index(
        "ix_submission_authorizations_candidate_id", table_name="submission_authorizations"
    )
    op.drop_index(
        "ix_submission_authorizations_application_id", table_name="submission_authorizations"
    )
    op.drop_table("submission_authorizations")

    with op.batch_alter_table("human_actions") as batch:
        batch.drop_constraint("fk_human_action_browser_session", type_="foreignkey")
        for column_name in (
            "completed_at",
            "expires_at",
            "screenshot_uri",
            "browser_session_id",
            "status",
            "kind",
        ):
            batch.drop_column(column_name)

    for table_name, constraint_name in reversed(
        (
            ("application_documents", "fk_application_document_scope"),
            ("application_answers", "fk_application_answer_scope"),
            ("application_events", "fk_application_event_scope"),
            ("security_events", "fk_security_event_application_scope"),
            ("browser_sessions", "fk_browser_session_scope"),
            ("human_actions", "fk_human_action_scope"),
            ("interviews", "fk_interview_scope"),
            ("offers", "fk_offer_scope"),
            ("agent_reviews", "fk_agent_review_scope"),
        )
    ):
        with op.batch_alter_table(table_name) as batch:
            batch.drop_constraint(constraint_name, type_="foreignkey")
    with op.batch_alter_table("applications") as batch:
        batch.drop_constraint("fk_application_candidate_score", type_="foreignkey")
        batch.drop_constraint("uq_application_scope", type_="unique")
        for column_name in (
            "submitted_at",
            "confirmation_reference",
            "archive_uri",
            "state_version",
        ):
            batch.drop_column(column_name)
    with op.batch_alter_table("candidate_job_scores") as batch:
        batch.drop_constraint("uq_candidate_job_score_scope", type_="unique")
