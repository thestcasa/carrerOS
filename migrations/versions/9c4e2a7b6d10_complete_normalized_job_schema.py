"""complete normalized job schema

Revision ID: 9c4e2a7b6d10
Revises: f3c5d8e9012a
Create Date: 2026-08-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c4e2a7b6d10"
down_revision: str | None = "f3c5d8e9012a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("global_jobs", sa.Column("company_stage", sa.String(length=100)))
    op.add_column("global_jobs", sa.Column("team", sa.String(length=255)))
    op.add_column("global_jobs", sa.Column("required_experience_years_min", sa.Integer()))
    op.add_column("global_jobs", sa.Column("required_experience_years_max", sa.Integer()))
    op.add_column("global_jobs", sa.Column("salary_source", sa.String(length=255)))
    op.add_column("global_jobs", sa.Column("visa_requirements", sa.Text()))
    op.add_column("global_jobs", sa.Column("work_authorization_requirements", sa.Text()))
    op.add_column("global_jobs", sa.Column("expected_start_date", sa.Date()))


def downgrade() -> None:
    op.drop_column("global_jobs", "expected_start_date")
    op.drop_column("global_jobs", "work_authorization_requirements")
    op.drop_column("global_jobs", "visa_requirements")
    op.drop_column("global_jobs", "salary_source")
    op.drop_column("global_jobs", "required_experience_years_max")
    op.drop_column("global_jobs", "required_experience_years_min")
    op.drop_column("global_jobs", "team")
    op.drop_column("global_jobs", "company_stage")
