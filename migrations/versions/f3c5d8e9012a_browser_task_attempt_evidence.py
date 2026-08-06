"""add browser task attempt evidence

Revision ID: f3c5d8e9012a
Revises: e2b4c7d8f901
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3c5d8e9012a"
down_revision: str | None = "e2b4c7d8f901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _restore_sqlite_workflow_task_fences() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    for operation in ("INSERT", "UPDATE"):
        suffix = operation.casefold()
        op.execute(f"DROP TRIGGER IF EXISTS trg_workflow_tasks_candidate_not_deleted_{suffix}")
        op.execute(
            f"""
            CREATE TRIGGER trg_workflow_tasks_candidate_not_deleted_{suffix}
            BEFORE {operation} ON workflow_tasks
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
    op.add_column("workflow_tasks", sa.Column("last_error_category", sa.String(length=64)))
    op.add_column("workflow_tasks", sa.Column("last_error_retryable", sa.Boolean()))
    op.add_column(
        "workflow_tasks",
        sa.Column("attempt_history", sa.JSON(), nullable=False, server_default="[]"),
    )
    _restore_sqlite_workflow_task_fences()


def downgrade() -> None:
    op.drop_column("workflow_tasks", "attempt_history")
    op.drop_column("workflow_tasks", "last_error_retryable")
    op.drop_column("workflow_tasks", "last_error_category")
    _restore_sqlite_workflow_task_fences()
