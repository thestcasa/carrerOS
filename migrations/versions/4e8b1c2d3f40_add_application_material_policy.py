"""add application material policy

Revision ID: 4e8b1c2d3f40
Revises: 9c4e2a7b6d10
Create Date: 2026-08-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4e8b1c2d3f40"
down_revision: str | None = "9c4e2a7b6d10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("material_policy", sa.JSON(), nullable=False, server_default="{}"),
    )
    connection = op.get_bind()
    applications = sa.table(
        "applications",
        sa.column("id", sa.Uuid()),
        sa.column("job_id", sa.Uuid()),
        sa.column("material_policy", sa.JSON()),
    )
    documents = sa.table(
        "application_documents",
        sa.column("application_id", sa.Uuid()),
        sa.column("kind", sa.String()),
    )
    job_versions = sa.table(
        "job_versions",
        sa.column("job_id", sa.Uuid()),
        sa.column("version", sa.Integer()),
        sa.column("payload_sha256", sa.String(length=64)),
    )
    cover_applications = {
        row.application_id
        for row in connection.execute(sa.select(documents.c.application_id, documents.c.kind))
        if str(row.kind).casefold() in {"cover_letter", "documentkind.cover_letter"}
    }
    latest_jobs: dict[object, tuple[int, str]] = {}
    for row in connection.execute(
        sa.select(
            job_versions.c.job_id,
            job_versions.c.version,
            job_versions.c.payload_sha256,
        ).order_by(job_versions.c.version)
    ):
        latest_jobs[row.job_id] = (row.version, row.payload_sha256)
    for row in connection.execute(sa.select(applications.c.id, applications.c.job_id)):
        application_id = row.id
        included = application_id in cover_applications
        job_identity = latest_jobs.get(row.job_id)
        if job_identity is None:
            continue
        connection.execute(
            sa.update(applications)
            .where(applications.c.id == application_id)
            .values(
                material_policy={
                    "schema_version": "1.0",
                    "generator_version": "legacy_material_unknown",
                    "job_version": job_identity[0],
                    "job_payload_sha256": job_identity[1],
                    "cv_template_id": "legacy-configured",
                    "cv_template_version": "unknown",
                    "selected_experience_ids": [],
                    "selected_project_ids": [],
                    "cover_letter": {
                        "included": included,
                        "reason": "legacy_document_present" if included else None,
                        "selected_experience_ids": [],
                        "selected_project_ids": [],
                        "minimum_words": 50,
                        "maximum_words": 2000,
                    },
                }
            )
        )


def downgrade() -> None:
    op.drop_column("applications", "material_policy")
