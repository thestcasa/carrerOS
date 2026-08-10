"""make administrative audit records immutable

Revision ID: 8e4b6c1d9a20
Revises: 6a9d4e2f7b10
Create Date: 2026-08-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "8e4b6c1d9a20"
down_revision: str | None = "6a9d4e2f7b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE FUNCTION careeros_reject_administrative_audit_update()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'administrative audit records are append-only'
                    USING ERRCODE = 'integrity_constraint_violation';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_administrative_audit_records_append_only
            BEFORE UPDATE ON administrative_audit_records
            FOR EACH ROW EXECUTE FUNCTION careeros_reject_administrative_audit_update()
            """
        )
    elif dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER trg_administrative_audit_records_append_only
            BEFORE UPDATE ON administrative_audit_records
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'administrative audit records are append-only');
            END
            """
        )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            "DROP TRIGGER trg_administrative_audit_records_append_only "
            "ON administrative_audit_records"
        )
        op.execute("DROP FUNCTION careeros_reject_administrative_audit_update()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER trg_administrative_audit_records_append_only")
