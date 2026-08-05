"""allow unmatched correspondence to fail closed

Revision ID: e70a9cd81b12
Revises: d302b1f4ac09
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e70a9cd81b12"
down_revision: str | None = "d302b1f4ac09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("correspondence_records") as batch_op:
        batch_op.alter_column(
            "application_id",
            existing_type=sa.Uuid(),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("correspondence_records") as batch_op:
        batch_op.alter_column(
            "application_id",
            existing_type=sa.Uuid(),
            nullable=False,
        )
