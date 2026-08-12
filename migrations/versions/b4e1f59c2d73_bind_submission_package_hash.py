"""bind submission authorizations to exact package hashes

Revision ID: b4e1f59c2d73
Revises: a71c302de864
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4e1f59c2d73"
down_revision: str | None = "a71c302de864"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "submission_authorizations",
        sa.Column("package_sha256", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("submission_authorizations", "package_sha256")
