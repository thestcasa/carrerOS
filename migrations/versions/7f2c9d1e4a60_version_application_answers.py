"""version application answers and bind review lineage

Revision ID: 7f2c9d1e4a60
Revises: 4e8b1c2d3f40
Create Date: 2026-08-06
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7f2c9d1e4a60"
down_revision: str | None = "4e8b1c2d3f40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _restore_sqlite_candidate_fences() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    for operation in ("INSERT", "UPDATE"):
        suffix = operation.casefold()
        op.execute(f"DROP TRIGGER IF EXISTS trg_application_answers_candidate_not_deleted_{suffix}")
        op.execute(
            f"""
            CREATE TRIGGER trg_application_answers_candidate_not_deleted_{suffix}
            BEFORE {operation} ON application_answers
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


def _create_append_only_trigger() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE FUNCTION careeros_reject_application_answer_update()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'application answers are append-only'
                    USING ERRCODE = 'integrity_constraint_violation';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE FUNCTION careeros_reject_application_answer_delete()
            RETURNS trigger AS $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM candidate_deletion_records
                    WHERE candidate_id = OLD.candidate_id
                ) THEN
                    RAISE EXCEPTION 'application answer history is append-only'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                RETURN OLD;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_application_answers_delete_guard
            BEFORE DELETE ON application_answers
            FOR EACH ROW EXECUTE FUNCTION careeros_reject_application_answer_delete()
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_application_answers_append_only
            BEFORE UPDATE ON application_answers
            FOR EACH ROW EXECUTE FUNCTION careeros_reject_application_answer_update()
            """
        )
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_application_answers_append_only")
        op.execute(
            """
            CREATE TRIGGER trg_application_answers_append_only
            BEFORE UPDATE ON application_answers
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'application answers are append-only');
            END
            """
        )
        op.execute("DROP TRIGGER IF EXISTS trg_application_answers_delete_guard")
        op.execute(
            """
            CREATE TRIGGER trg_application_answers_delete_guard
            BEFORE DELETE ON application_answers
            FOR EACH ROW
            WHEN NOT EXISTS (
                SELECT 1 FROM candidate_deletion_records
                WHERE candidate_id = OLD.candidate_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'application answer history is append-only');
            END
            """
        )


def _drop_append_only_trigger() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER trg_application_answers_delete_guard ON application_answers")
        op.execute("DROP TRIGGER trg_application_answers_append_only ON application_answers")
        op.execute("DROP FUNCTION careeros_reject_application_answer_delete()")
        op.execute("DROP FUNCTION careeros_reject_application_answer_update()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_application_answers_delete_guard")
        op.execute("DROP TRIGGER IF EXISTS trg_application_answers_append_only")


def _snapshot_bindings() -> dict[object, tuple[object, str, str]]:
    connection = op.get_bind()
    artifacts = sa.table(
        "application_artifacts",
        sa.column("application_id", sa.Uuid()),
        sa.column("kind", sa.String()),
        sa.column("artifact_metadata", sa.JSON()),
    )
    snapshots = sa.table(
        "candidate_snapshot_records",
        sa.column("id", sa.Uuid()),
        sa.column("application_id", sa.Uuid()),
        sa.column("profile_version", sa.String()),
        sa.column("sha256", sa.String()),
    )
    snapshot_rows = {
        (row.application_id, str(row.id)): row for row in connection.execute(sa.select(snapshots))
    }
    candidates: dict[object, set[str]] = {}
    for row in connection.execute(sa.select(artifacts)):
        if not str(row.kind).startswith("render_report_") or not isinstance(
            row.artifact_metadata, dict
        ):
            continue
        snapshot_id = row.artifact_metadata.get("candidate_snapshot_id")
        if snapshot_id is not None:
            candidates.setdefault(row.application_id, set()).add(str(snapshot_id))
    bindings: dict[object, tuple[object, str, str]] = {}
    for application_id, snapshot_ids in candidates.items():
        if len(snapshot_ids) != 1:
            continue
        snapshot_id = next(iter(snapshot_ids))
        row = snapshot_rows.get((application_id, snapshot_id))
        if row is not None:
            bindings[application_id] = (row.id, row.profile_version, row.sha256)
    return bindings


def upgrade() -> None:
    op.add_column("application_answers", sa.Column("version", sa.Integer(), nullable=True))
    op.add_column("application_answers", sa.Column("sha256", sa.String(64), nullable=True))
    op.add_column("application_answers", sa.Column("actor_id", sa.String(64), nullable=True))
    op.add_column("application_answers", sa.Column("revision_kind", sa.String(32), nullable=True))
    op.add_column("application_answers", sa.Column("previous_answer_id", sa.Uuid(), nullable=True))
    op.add_column("application_answers", sa.Column("reason", sa.Text(), nullable=True))
    op.add_column(
        "application_answers", sa.Column("candidate_snapshot_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "application_answers",
        sa.Column("candidate_snapshot_version", sa.String(32), nullable=True),
    )
    op.add_column(
        "application_answers",
        sa.Column("candidate_snapshot_sha256", sa.String(64), nullable=True),
    )

    connection = op.get_bind()
    answers = sa.table(
        "application_answers",
        sa.column("id", sa.Uuid()),
        sa.column("application_id", sa.Uuid()),
        sa.column("answer", sa.Text()),
        sa.column("approved_source_key", sa.String()),
        sa.column("supported", sa.Boolean()),
        sa.column("version", sa.Integer()),
        sa.column("sha256", sa.String()),
        sa.column("actor_id", sa.String()),
        sa.column("revision_kind", sa.String()),
        sa.column("candidate_snapshot_id", sa.Uuid()),
        sa.column("candidate_snapshot_version", sa.String()),
        sa.column("candidate_snapshot_sha256", sa.String()),
    )
    bindings = _snapshot_bindings()
    for row in connection.execute(
        sa.select(answers.c.id, answers.c.application_id, answers.c.answer)
    ):
        values: dict[str, object] = {
            "version": 1,
            "sha256": hashlib.sha256(row.answer.encode("utf-8")).hexdigest(),
            "actor_id": "legacy-answer-unknown",
            "revision_kind": "legacy_unknown",
        }
        binding = bindings.get(row.application_id)
        if binding is not None:
            values.update(
                candidate_snapshot_id=binding[0],
                candidate_snapshot_version=binding[1],
                candidate_snapshot_sha256=binding[2],
            )
        connection.execute(sa.update(answers).where(answers.c.id == row.id).values(**values))
    connection.execute(
        sa.update(answers)
        .where(answers.c.supported.is_(True), answers.c.approved_source_key.is_(None))
        .values(supported=False)
    )

    with op.batch_alter_table("application_answers") as batch:
        batch.alter_column("version", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("sha256", existing_type=sa.String(64), nullable=False)
        batch.alter_column("actor_id", existing_type=sa.String(64), nullable=False)
        batch.alter_column("revision_kind", existing_type=sa.String(32), nullable=False)
        batch.drop_constraint("uq_application_answer", type_="unique")
        batch.create_unique_constraint(
            "uq_application_answer_version",
            ["candidate_id", "application_id", "question_key", "version"],
        )
        batch.create_unique_constraint(
            "uq_application_answer_scope",
            ["candidate_id", "application_id", "question_key", "id"],
        )
        batch.create_unique_constraint(
            "uq_application_answer_previous",
            ["candidate_id", "application_id", "question_key", "previous_answer_id"],
        )
        batch.create_foreign_key(
            "fk_application_answer_previous_scope",
            "application_answers",
            ["candidate_id", "application_id", "question_key", "previous_answer_id"],
            ["candidate_id", "application_id", "question_key", "id"],
        )
        batch.create_check_constraint("ck_application_answer_version_positive", "version >= 1")
        batch.create_check_constraint(
            "ck_application_answer_lineage",
            "(version = 1 AND previous_answer_id IS NULL) OR "
            "(version > 1 AND previous_answer_id IS NOT NULL)",
        )
        batch.create_check_constraint(
            "ck_application_answer_revision_kind",
            "revision_kind IN ('generated', 'manual', 'withdrawn', 'legacy_unknown')",
        )
        batch.create_check_constraint(
            "ck_application_answer_supported_source",
            "supported = false OR approved_source_key IS NOT NULL",
        )
    op.create_index(
        "ix_application_answers_latest",
        "application_answers",
        ["candidate_id", "application_id", "question_key", "version"],
    )
    _restore_sqlite_candidate_fences()
    _create_append_only_trigger()


def downgrade() -> None:
    connection = op.get_bind()
    duplicate = connection.execute(
        sa.text(
            """
            SELECT 1
            FROM application_answers
            GROUP BY candidate_id, application_id, question_key
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError("answer revision history must be removed before downgrade")
    _drop_append_only_trigger()
    op.drop_index("ix_application_answers_latest", table_name="application_answers")
    with op.batch_alter_table("application_answers") as batch:
        batch.drop_constraint("fk_application_answer_previous_scope", type_="foreignkey")
        batch.drop_constraint("uq_application_answer_previous", type_="unique")
        batch.drop_constraint("uq_application_answer_scope", type_="unique")
        batch.drop_constraint("uq_application_answer_version", type_="unique")
        batch.drop_constraint("ck_application_answer_supported_source", type_="check")
        batch.drop_constraint("ck_application_answer_revision_kind", type_="check")
        batch.drop_constraint("ck_application_answer_lineage", type_="check")
        batch.drop_constraint("ck_application_answer_version_positive", type_="check")
        batch.create_unique_constraint(
            "uq_application_answer", ["candidate_id", "application_id", "question_key"]
        )
        batch.drop_column("candidate_snapshot_sha256")
        batch.drop_column("candidate_snapshot_version")
        batch.drop_column("candidate_snapshot_id")
        batch.drop_column("reason")
        batch.drop_column("previous_answer_id")
        batch.drop_column("revision_kind")
        batch.drop_column("actor_id")
        batch.drop_column("sha256")
        batch.drop_column("version")
    _restore_sqlite_candidate_fences()
