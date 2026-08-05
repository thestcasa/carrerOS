"""milestone 2 job discovery

Revision ID: 5d91d7e52a21
Revises: 01b5a2f6e718
Create Date: 2026-08-04 22:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5d91d7e52a21"
down_revision: str | None = "01b5a2f6e718"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = (
        sa.Column("normalized_title", sa.String(length=255), nullable=True),
        sa.Column("normalized_location", sa.String(length=255), nullable=True),
        sa.Column("company_domain", sa.String(length=255), nullable=True),
        sa.Column("requisition_id", sa.String(length=255), nullable=True),
        sa.Column("application_url", sa.Text(), nullable=True),
        sa.Column("ats_platform", sa.String(length=50), nullable=True),
        sa.Column("remote_policy", sa.String(length=50), nullable=True),
        sa.Column("employment_type", sa.String(length=50), nullable=True),
        sa.Column("seniority", sa.String(length=50), nullable=True),
        sa.Column("description_normalized", sa.Text(), nullable=True),
        sa.Column("required_skills", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("preferred_skills", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("required_languages", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("salary_min", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("salary_max", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("salary_currency", sa.String(length=3), nullable=True),
        sa.Column("salary_period", sa.String(length=50), nullable=True),
        sa.Column(
            "source_trust_level",
            sa.String(length=32),
            nullable=False,
            server_default="unverified",
        ),
        sa.Column("verified_open_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("semantic_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("security_findings", sa.JSON(), nullable=False, server_default="[]"),
    )
    for column in columns:
        op.add_column("global_jobs", column)
    for name, fields in (
        ("ix_global_jobs_normalized_title", ["normalized_title"]),
        ("ix_global_jobs_company_domain", ["company_domain"]),
        ("ix_global_jobs_requisition_id", ["requisition_id"]),
        ("ix_global_jobs_ats_platform", ["ats_platform"]),
        ("ix_global_jobs_semantic_fingerprint", ["semantic_fingerprint"]),
    ):
        op.create_index(name, "global_jobs", fields, unique=False)
    op.create_table(
        "job_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("normalized_payload", sa.JSON(), nullable=False),
        sa.Column("source_payload", sa.JSON(), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["global_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "payload_sha256", name="uq_job_version_payload"),
        sa.UniqueConstraint("job_id", "version", name="uq_job_version"),
    )
    op.create_index("ix_job_versions_job_id", "job_versions", ["job_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_job_versions_job_id", table_name="job_versions")
    op.drop_table("job_versions")
    for name in (
        "ix_global_jobs_semantic_fingerprint",
        "ix_global_jobs_ats_platform",
        "ix_global_jobs_requisition_id",
        "ix_global_jobs_company_domain",
        "ix_global_jobs_normalized_title",
    ):
        op.drop_index(name, table_name="global_jobs")
    for name in (
        "security_findings",
        "semantic_fingerprint",
        "deadline",
        "posted_at",
        "verified_open_at",
        "source_trust_level",
        "salary_period",
        "salary_currency",
        "salary_max",
        "salary_min",
        "required_languages",
        "preferred_skills",
        "required_skills",
        "description_normalized",
        "seniority",
        "employment_type",
        "remote_policy",
        "ats_platform",
        "application_url",
        "requisition_id",
        "company_domain",
        "normalized_location",
        "normalized_title",
    ):
        op.drop_column("global_jobs", name)
