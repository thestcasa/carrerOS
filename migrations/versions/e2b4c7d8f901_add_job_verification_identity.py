"""add source verification evidence and candidate submission identity

Revision ID: e2b4c7d8f901
Revises: d1a7e6c9420b
Create Date: 2026-08-05
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence
from urllib.parse import urlsplit

import sqlalchemy as sa
from alembic import context, op

revision: str = "e2b4c7d8f901"
down_revision: str | None = "d1a7e6c9420b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _normalize(value: str | None) -> str:
    if value is None:
        return ""
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", ascii_value.casefold()))


def _application_url(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        return ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    path = parsed.path.rstrip("/") or "/"
    return f"https://{parsed.hostname.casefold()}{port}{path}"


def _sha(*values: str | None) -> str:
    return hashlib.sha256("\x1f".join(_normalize(value) for value in values).encode()).hexdigest()


def _restore_sqlite_application_fences() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    for operation in ("INSERT", "UPDATE"):
        suffix = operation.casefold()
        op.execute(f"DROP TRIGGER IF EXISTS trg_applications_candidate_not_deleted_{suffix}")
        op.execute(
            f"""
            CREATE TRIGGER trg_applications_candidate_not_deleted_{suffix}
            BEFORE {operation} ON applications
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
    if context.is_offline_mode():
        raise RuntimeError(
            "e2b4c7d8f901 requires an online connection to collision-check application identities"
        )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT a.id, a.candidate_id, j.company, j.title, j.normalized_title,
                   j.location, j.normalized_location, j.requisition_id, j.application_url
            FROM applications AS a
            JOIN global_jobs AS j ON j.id = a.job_id
            """
        )
    ).mappings()
    seen: set[tuple[str, str]] = set()
    prepared: list[dict[str, object]] = []
    for row in rows:
        title = row["normalized_title"] or row["title"]
        location = row["normalized_location"] or row["location"]
        duplicate_hash = _sha(
            row["candidate_id"],
            row["company"],
            title,
            location,
            row["requisition_id"],
        )
        if row["requisition_id"]:
            identity_hash = _sha(row["candidate_id"], row["company"], row["requisition_id"])
        elif normalized_url := _application_url(row["application_url"]):
            identity_hash = _sha(row["candidate_id"], row["company"], normalized_url)
        else:
            identity_hash = _sha(row["candidate_id"], row["company"], title, location, None)
        identity = (row["candidate_id"], identity_hash)
        if identity in seen:
            raise RuntimeError("equivalent candidate applications must be resolved before upgrade")
        seen.add(identity)
        prepared.append(
            {
                "application_id": row["id"],
                "duplicate_hash": duplicate_hash,
                "submission_identity_hash": identity_hash,
            }
        )

    op.add_column("global_jobs", sa.Column("verification_status", sa.String(16)))
    op.add_column("global_jobs", sa.Column("verification_checked_at", sa.DateTime(timezone=True)))
    op.add_column("global_jobs", sa.Column("verification_evidence_sha256", sa.String(64)))
    op.add_column(
        "global_jobs",
        sa.Column("verification_evidence", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index(
        op.f("ix_global_jobs_verification_status"),
        "global_jobs",
        ["verification_status"],
        unique=False,
    )
    op.add_column("applications", sa.Column("duplicate_hash", sa.String(64)))
    op.add_column("applications", sa.Column("submission_identity_hash", sa.String(64)))
    op.create_index(
        op.f("ix_applications_duplicate_hash"),
        "applications",
        ["duplicate_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_applications_submission_identity_hash"),
        "applications",
        ["submission_identity_hash"],
        unique=False,
    )

    for values in prepared:
        connection.execute(
            sa.text(
                """
                UPDATE applications
                SET duplicate_hash = :duplicate_hash,
                    submission_identity_hash = :submission_identity_hash
                WHERE id = :application_id
                """
            ),
            values,
        )

    with op.batch_alter_table("applications") as batch:
        batch.alter_column("duplicate_hash", existing_type=sa.String(64), nullable=False)
        batch.alter_column("submission_identity_hash", existing_type=sa.String(64), nullable=False)
        batch.create_unique_constraint(
            "uq_candidate_application_submission_identity",
            ["candidate_id", "submission_identity_hash"],
        )
    _restore_sqlite_application_fences()


def downgrade() -> None:
    with op.batch_alter_table("applications") as batch:
        batch.drop_constraint("uq_candidate_application_submission_identity", type_="unique")
    op.drop_index(op.f("ix_applications_submission_identity_hash"), table_name="applications")
    op.drop_index(op.f("ix_applications_duplicate_hash"), table_name="applications")
    op.drop_column("applications", "submission_identity_hash")
    op.drop_column("applications", "duplicate_hash")
    op.drop_index(op.f("ix_global_jobs_verification_status"), table_name="global_jobs")
    op.drop_column("global_jobs", "verification_evidence")
    op.drop_column("global_jobs", "verification_evidence_sha256")
    op.drop_column("global_jobs", "verification_checked_at")
    op.drop_column("global_jobs", "verification_status")
    _restore_sqlite_application_fences()
