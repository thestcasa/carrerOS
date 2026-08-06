from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import shutil
import stat
from base64 import b64encode
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Table, and_, delete, exists, func, or_, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.archive import canonical_json_bytes
from app.candidates.service import CandidateService, CandidateUpdateError
from app.domain.enums import ApplicationState
from app.domain.models import (
    AdministrativeAuditRecord,
    Application,
    ApplicationArtifact,
    ApplicationDocument,
    ApplicationEvent,
    Base,
    BrowserSession,
    CandidateDeletionRecord,
    CandidateSettingsRecord,
    CandidateSnapshotRecord,
    HumanAction,
)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class CandidateDeletionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CandidateDeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    confirmation: str = Field(min_length=3, max_length=64)
    delete_archives: Literal[True]


class CandidateDeletionView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    status: Literal["deleting", "failed", "completed"]
    deleted_rows: dict[str, int]
    deleted_paths: tuple[str, ...]
    error_code: str | None
    requested_at: datetime
    completed_at: datetime | None


class CandidateExportEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_base64: str


class CandidateExportView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    candidate_id: str
    created_at: datetime
    files: tuple[CandidateExportEntry, ...]
    database: dict[str, list[dict[str, Any]]]
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class CandidateLifecycleService:
    """Executes candidate erasure while retaining a minimal durable accountability record."""

    _EXPORT_FILE_LIMIT = 32 * 1024 * 1024
    _EXPORT_TOTAL_LIMIT = 512 * 1024 * 1024
    _EXPORT_FILE_COUNT_LIMIT = 10_000

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        candidates: CandidateService,
        runtime_root: Path,
    ) -> None:
        self._sessions = session_factory
        self._candidates = candidates
        self._runtime_root = runtime_root.resolve()

    def export_candidate(
        self, candidate_id: str, *, now: datetime | None = None
    ) -> CandidateExportView:
        with self._candidates.lifecycle_read(candidate_id):
            if self.is_deleted(candidate_id):
                raise CandidateDeletionError(
                    "candidate_deleted", "Candidate data is no longer available."
                )
            with self._sessions() as session:
                if session.get_bind().dialect.name == "postgresql":
                    session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                database = self._export_database(session, candidate_id)
                files = self._export_files(
                    candidate_id, self._candidates.configuration_directory(candidate_id)
                )
            created_at = now or datetime.now(UTC)
            manifest_sha256 = hashlib.sha256(
                canonical_json_bytes(
                    {
                        "schema_version": "1.0",
                        "candidate_id": candidate_id,
                        "created_at": created_at,
                        "files": [
                            {"path": item.path, "size": item.size, "sha256": item.sha256}
                            for item in files
                        ],
                        "database_sha256": hashlib.sha256(
                            canonical_json_bytes(database)
                        ).hexdigest(),
                    }
                )
            ).hexdigest()
            return CandidateExportView(
                candidate_id=candidate_id,
                created_at=created_at,
                files=files,
                database=database,
                manifest_sha256=manifest_sha256,
            )

    def _export_files(
        self, candidate_id: str, configuration_root: Path
    ) -> tuple[CandidateExportEntry, ...]:
        roots = (
            (configuration_root, "configuration"),
            (
                self._runtime_root / "candidates" / candidate_id / "application_archive",
                "working_artifacts",
            ),
            (
                self._runtime_root / "application_archive" / candidate_id,
                "application_archive",
            ),
            (
                self._runtime_root / "candidates" / candidate_id / "browser_evidence",
                "browser_attempt_evidence",
            ),
        )
        entries: list[CandidateExportEntry] = []
        total_size = 0
        for root, prefix in roots:
            if not root.exists():
                if root.is_symlink():
                    raise CandidateDeletionError(
                        "unsafe_candidate_path", "Candidate export root is unsafe."
                    )
                continue
            if root.is_symlink() or not root.is_dir():
                raise CandidateDeletionError(
                    "unsafe_candidate_path", "Candidate export root is unsafe."
                )
            for path in sorted(root.rglob("*")):
                if path.is_dir() and not path.is_symlink():
                    continue
                relative = path.relative_to(root)
                content = self._read_export_file(root, relative)
                total_size += len(content)
                if (
                    len(entries) >= self._EXPORT_FILE_COUNT_LIMIT
                    or total_size > self._EXPORT_TOTAL_LIMIT
                ):
                    raise CandidateDeletionError(
                        "candidate_export_too_large", "Candidate export exceeds safe limits."
                    )
                entries.append(
                    CandidateExportEntry(
                        path=f"{prefix}/{relative.as_posix()}",
                        size=len(content),
                        sha256=hashlib.sha256(content).hexdigest(),
                        content_base64=b64encode(content).decode("ascii"),
                    )
                )
        sessions_root = self._runtime_root / "candidates" / candidate_id / "sessions"
        if sessions_root.exists() or sessions_root.is_symlink():
            if sessions_root.is_symlink() or not sessions_root.is_dir():
                raise CandidateDeletionError(
                    "unsafe_candidate_path", "Candidate browser evidence root is unsafe."
                )
            evidence_names = {
                "final-page.json",
                "final-page.png",
                "metadata.json",
                "playwright-final-page.html",
                "playwright-final-page.png",
                "playwright-session.json",
                "snapshot.html",
                "screenshot.png",
            }
            for path in sorted(sessions_root.glob("*/*")):
                if path.name not in evidence_names:
                    continue
                relative = path.relative_to(sessions_root)
                content = self._read_export_file(sessions_root, relative)
                if path.name.endswith(".json"):
                    content = self._sanitize_export_json(content)
                total_size += len(content)
                if (
                    len(entries) >= self._EXPORT_FILE_COUNT_LIMIT
                    or total_size > self._EXPORT_TOTAL_LIMIT
                ):
                    raise CandidateDeletionError(
                        "candidate_export_too_large", "Candidate export exceeds safe limits."
                    )
                entries.append(
                    CandidateExportEntry(
                        path=f"browser_evidence/{relative.as_posix()}",
                        size=len(content),
                        sha256=hashlib.sha256(content).hexdigest(),
                        content_base64=b64encode(content).decode("ascii"),
                    )
                )
        return tuple(entries)

    def _sanitize_export_json(self, content: bytes) -> bytes:
        try:
            value = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CandidateDeletionError(
                "candidate_export_failed", "Candidate browser evidence is invalid."
            ) from exc
        return canonical_json_bytes(self._json_value(value))

    def _read_export_file(self, root: Path, relative: Path) -> bytes:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            parts = relative.parts
            if not parts or any(part in {"", ".", ".."} for part in parts):
                raise CandidateDeletionError(
                    "unsafe_candidate_path", "Candidate export path is unsafe."
                )
            for part in parts[:-1]:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
                os.close(descriptor)
                descriptor = child
            file_descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
            try:
                before = os.fstat(file_descriptor)
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                    raise CandidateDeletionError(
                        "unsafe_candidate_path", "Candidate export file is unsafe."
                    )
                chunks: list[bytes] = []
                size = 0
                while chunk := os.read(file_descriptor, 1024 * 1024):
                    size += len(chunk)
                    if size > self._EXPORT_FILE_LIMIT:
                        raise CandidateDeletionError(
                            "candidate_export_too_large",
                            "A candidate export file exceeds safe limits.",
                        )
                    chunks.append(chunk)
                after = os.fstat(file_descriptor)
                identity_before = (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                )
                identity_after = (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                )
                if identity_before != identity_after or size != after.st_size:
                    raise CandidateDeletionError(
                        "candidate_export_changed", "Candidate data changed during export."
                    )
                return b"".join(chunks)
            finally:
                os.close(file_descriptor)
        except OSError as exc:
            raise CandidateDeletionError(
                "unsafe_candidate_path", "Candidate export path is unsafe."
            ) from exc
        finally:
            os.close(descriptor)

    def _export_database(
        self, session: Session, candidate_id: str
    ) -> dict[str, list[dict[str, Any]]]:
        output: dict[str, list[dict[str, Any]]] = {}
        referenced_jobs: set[UUID] = set()
        for table in Base.metadata.sorted_tables:
            if "candidate_id" not in table.c or table.name == "candidate_deletion_records":
                continue
            rows = [
                dict(row)
                for row in session.execute(
                    select(table).where(table.c.candidate_id == candidate_id)
                ).mappings()
            ]
            for row in rows:
                self._collect_job_ids(row, referenced_jobs)
            sanitized = [self._sanitize_database_row(table, row) for row in rows]
            output[table.name] = sorted(
                sanitized, key=lambda item: json.dumps(item, sort_keys=True)
            )
        for table_name in ("global_jobs", "job_versions"):
            table = Base.metadata.tables[table_name]
            job_column = table.c.id if table_name == "global_jobs" else table.c.job_id
            shared_rows = session.execute(
                select(table).where(job_column.in_(referenced_jobs))
            ).mappings()
            output[table_name] = sorted(
                (self._sanitize_database_row(table, dict(row)) for row in shared_rows),
                key=lambda item: json.dumps(item, sort_keys=True),
            )
        return output

    @classmethod
    def _collect_job_ids(cls, value: Any, output: set[UUID], key: str | None = None) -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                cls._collect_job_ids(child, output, str(child_key))
        elif isinstance(value, (list, tuple)):
            for child in value:
                cls._collect_job_ids(child, output, key)
        elif key in {"job_id", "job_ids"}:
            with suppress(ValueError, TypeError):
                output.add(UUID(str(value)))

    @classmethod
    def _sanitize_database_row(cls, table: Table, row: dict[str, Any]) -> dict[str, Any]:
        excluded = {key for key in row if cls._excluded_export_key(key)}
        return {key: cls._json_value(value) for key, value in row.items() if key not in excluded}

    @staticmethod
    def _excluded_export_key(key: str) -> bool:
        return (
            "idempotency_key" in key
            or key.endswith("_path")
            or key.endswith("_directory")
            or key.endswith("_uri")
            or key
            in {
                "authorization_id",
                "external_session_ref",
                "session_directory",
            }
        )

    @classmethod
    def _json_value(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, (UUID, Decimal, Enum)):
            return str(value.value if isinstance(value, Enum) else value)
        if isinstance(value, bytes):
            return b64encode(value).decode("ascii")
        if isinstance(value, dict):
            return {
                str(key): cls._json_value(item)
                for key, item in value.items()
                if not cls._excluded_export_key(str(key))
            }
        if isinstance(value, (list, tuple)):
            return [cls._json_value(item) for item in value]
        raise CandidateDeletionError(
            "candidate_export_failed", "Candidate database value cannot be exported safely."
        )

    def delete_candidate(
        self,
        candidate_id: str,
        command: CandidateDeletionRequest,
        idempotency_key: str,
        *,
        now: datetime | None = None,
    ) -> CandidateDeletionView:
        if candidate_id == "example_candidate":
            raise CandidateDeletionError(
                "protected_candidate", "The fictional onboarding template cannot be deleted."
            )
        if command.confirmation != candidate_id:
            raise CandidateDeletionError(
                "confirmation_mismatch", "Deletion confirmation must exactly match candidate ID."
            )
        if len(idempotency_key) < 8:
            raise CandidateDeletionError("invalid_idempotency_key", "Idempotency key is invalid.")
        request_sha256 = hashlib.sha256(
            json.dumps(
                {"candidate_id": candidate_id, **command.model_dump(mode="json")},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        idempotency_key_sha256 = hashlib.sha256(idempotency_key.encode()).hexdigest()
        with self._candidates.lifecycle_fence(candidate_id):
            existing = self._record(candidate_id)
            if existing is not None:
                self._validate_replay(existing, request_sha256)
                self._ensure_deletion_key_available(candidate_id, idempotency_key_sha256)
                if existing.status == "completed":
                    return self._view(existing)
            try:
                if existing is None and not self._candidates.is_deletion_marked(candidate_id):
                    self._candidates.get_config(candidate_id)
                self._begin(
                    candidate_id,
                    idempotency_key_sha256,
                    request_sha256,
                    now or datetime.now(UTC),
                )
                self._preflight_storage_references(candidate_id)
                deleted_rows = self._delete_database(candidate_id)
                deleted_paths = self._delete_files(candidate_id)
                self._verify_erased(candidate_id)
                return self._complete(
                    candidate_id, deleted_rows, deleted_paths, now or datetime.now(UTC)
                )
            except CandidateDeletionError as exc:
                self._fail(candidate_id, exc.code)
                raise
            except CandidateUpdateError as exc:
                self._fail(candidate_id, "unsafe_candidate_path")
                raise CandidateDeletionError(
                    "unsafe_candidate_path", "Candidate files could not be deleted safely."
                ) from exc
            except Exception as exc:
                self._fail(candidate_id, "candidate_deletion_failed")
                raise CandidateDeletionError(
                    "candidate_deletion_failed", "Candidate deletion did not complete."
                ) from exc

    def _begin(
        self,
        candidate_id: str,
        idempotency_key_sha256: str,
        request_sha256: str,
        requested_at: datetime,
    ) -> None:
        try:
            with self._sessions.begin() as session:
                record = session.get(CandidateDeletionRecord, candidate_id)
                key_owner = session.scalar(
                    select(CandidateDeletionRecord).where(
                        CandidateDeletionRecord.idempotency_key_sha256 == idempotency_key_sha256,
                        CandidateDeletionRecord.candidate_id != candidate_id,
                    )
                )
                if key_owner is not None:
                    raise CandidateDeletionError(
                        "idempotency_conflict",
                        "Candidate deletion key is already bound to another request.",
                    )
                if record is None:
                    record = CandidateDeletionRecord(
                        candidate_id=candidate_id,
                        idempotency_key_sha256=idempotency_key_sha256,
                        request_sha256=request_sha256,
                        status="deleting",
                        requested_at=requested_at,
                    )
                    session.add(record)
                    session.flush()
                    self._append_audit(
                        session,
                        candidate_id,
                        "candidate.deletion_started",
                        pseudonymize=True,
                    )
                else:
                    self._validate_replay(record, request_sha256)
                    record.status = "deleting"
                    record.error_code = None
                self._candidates.mark_for_deletion(candidate_id, request_sha256)
        except IntegrityError as exc:
            raise CandidateDeletionError(
                "idempotency_conflict", "Candidate deletion command is already in progress."
            ) from exc

    def _delete_database(self, candidate_id: str) -> dict[str, int]:
        with self._sessions.begin() as session:
            record = session.get(CandidateDeletionRecord, candidate_id)
            if record is None:
                raise CandidateDeletionError(
                    "candidate_deletion_failed", "Candidate deletion receipt is missing."
                )
            deleted_rows = {key: int(value) for key, value in record.deleted_rows.items()}
            excluded = {"candidate_deletion_records"}
            for table in reversed(Base.metadata.sorted_tables):
                if "candidate_id" not in table.c or table.name in excluded:
                    continue
                result = cast(
                    CursorResult[Any],
                    session.execute(delete(table).where(table.c.candidate_id == candidate_id)),
                )
                deleted_rows[table.name] = deleted_rows.get(table.name, 0) + max(result.rowcount, 0)
            record.deleted_rows = deleted_rows
        return deleted_rows

    def _delete_files(self, candidate_id: str) -> tuple[str, ...]:
        record = self._record(candidate_id)
        deleted = set(record.deleted_paths if record is not None else ())
        steps: tuple[tuple[str, Callable[[], bool]], ...] = (
            (
                "application_archive",
                lambda: self._delete_runtime_tree(
                    self._runtime_root / "application_archive", candidate_id
                ),
            ),
            (
                "candidate_runtime",
                lambda: self._delete_runtime_tree(self._runtime_root / "candidates", candidate_id),
            ),
            (
                "candidate_configuration",
                lambda: self._candidates.purge_deleted_configuration(candidate_id),
            ),
        )
        for label, operation in steps:
            if operation():
                deleted.add(label)
                self._persist_deleted_paths(candidate_id, deleted)
        return tuple(sorted(deleted))

    def _persist_deleted_paths(self, candidate_id: str, deleted: set[str]) -> None:
        with self._sessions.begin() as session:
            record = session.get(CandidateDeletionRecord, candidate_id)
            if record is not None:
                record.deleted_paths = sorted(deleted)

    def _preflight_storage_references(self, candidate_id: str) -> None:
        allowed_roots = (
            (self._runtime_root / "candidates" / candidate_id).absolute(),
            (self._runtime_root / "application_archive" / candidate_id).absolute(),
        )
        references: list[str] = []
        with self._sessions() as session:
            references.extend(
                value
                for value in session.scalars(
                    select(Application.archive_uri).where(
                        Application.candidate_id == candidate_id,
                        Application.archive_uri.is_not(None),
                    )
                )
                if value
            )
            for model, column in (
                (ApplicationArtifact, ApplicationArtifact.storage_uri),
                (ApplicationDocument, ApplicationDocument.storage_uri),
                (CandidateSnapshotRecord, CandidateSnapshotRecord.storage_uri),
                (BrowserSession, BrowserSession.external_session_ref),
                (HumanAction, HumanAction.screenshot_uri),
            ):
                references.extend(
                    value
                    for value in session.scalars(
                        select(column).where(
                            model.candidate_id == candidate_id, column.is_not(None)
                        )
                    )
                    if value
                )
        for reference in references:
            path = Path(reference).absolute().resolve()
            if not any(path.is_relative_to(root) for root in allowed_roots):
                raise CandidateDeletionError(
                    "unsafe_storage_reference",
                    "Candidate storage reference is outside the deletion roots.",
                )

    def _delete_runtime_tree(self, parent: Path, candidate_id: str) -> bool:
        if not parent.exists():
            if parent.is_symlink():
                raise CandidateDeletionError(
                    "unsafe_candidate_path", "Candidate runtime root is unsafe."
                )
            return False
        if (
            parent.is_symlink()
            or not parent.is_dir()
            or parent.resolve().parent != self._runtime_root
        ):
            raise CandidateDeletionError(
                "unsafe_candidate_path", "Candidate runtime root is unsafe."
            )
        target = parent / candidate_id
        quarantine = parent / f".deleting-{candidate_id}"
        target_present = target.exists() or target.is_symlink()
        quarantine_present = quarantine.exists() or quarantine.is_symlink()
        if target_present and quarantine_present:
            raise CandidateDeletionError(
                "unsafe_candidate_path", "Candidate runtime quarantine conflicts."
            )
        target = quarantine if quarantine_present else target
        if not (target.exists() or target.is_symlink()):
            return False
        if (
            target.is_symlink()
            or not target.is_dir()
            or target.parent != parent
            or target.resolve().parent != parent.resolve()
        ):
            raise CandidateDeletionError(
                "unsafe_candidate_path", "Candidate runtime path is unsafe."
            )
        self._reject_unsafe_tree(target)
        live = parent / candidate_id
        if target == live:
            live.rename(quarantine)
            target = quarantine
        shutil.rmtree(target)
        return True

    def _verify_erased(self, candidate_id: str) -> None:
        excluded = {"candidate_deletion_records"}
        with self._sessions() as session:
            for table in Base.metadata.sorted_tables:
                if "candidate_id" not in table.c or table.name in excluded:
                    continue
                remaining = session.scalar(
                    select(func.count())
                    .select_from(table)
                    .where(table.c.candidate_id == candidate_id)
                )
                if remaining:
                    raise CandidateDeletionError(
                        "candidate_deletion_incomplete", "Candidate database rows remain."
                    )
        for parent in (
            self._runtime_root / "application_archive",
            self._runtime_root / "candidates",
        ):
            live = parent / candidate_id
            quarantine = parent / f".deleting-{candidate_id}"
            if live.exists() or live.is_symlink() or quarantine.exists() or quarantine.is_symlink():
                raise CandidateDeletionError(
                    "candidate_deletion_incomplete", "Candidate runtime data remains."
                )
        if not self._candidates.deleted_configuration_absent(candidate_id):
            raise CandidateDeletionError(
                "candidate_deletion_incomplete", "Candidate configuration remains."
            )

    def _complete(
        self,
        candidate_id: str,
        deleted_rows: dict[str, int],
        deleted_paths: tuple[str, ...],
        completed_at: datetime,
    ) -> CandidateDeletionView:
        with self._sessions.begin() as session:
            record = session.get(CandidateDeletionRecord, candidate_id)
            if record is None:
                raise CandidateDeletionError(
                    "candidate_deletion_failed", "Candidate deletion receipt is missing."
                )
            record.status = "completed"
            record.deleted_rows = deleted_rows
            record.deleted_paths = list(deleted_paths)
            record.error_code = None
            record.completed_at = completed_at
            self._append_audit(
                session,
                candidate_id,
                "candidate.deletion_completed",
                pseudonymize=True,
            )
            session.flush()
            return self._view(record)

    def _fail(self, candidate_id: str, error_code: str) -> None:
        with self._sessions.begin() as session:
            record = session.get(CandidateDeletionRecord, candidate_id)
            if record is not None and record.status != "completed":
                record.status = "failed"
                record.error_code = error_code

    def _record(self, candidate_id: str) -> CandidateDeletionRecord | None:
        with self._sessions() as session:
            return session.get(CandidateDeletionRecord, candidate_id)

    def is_deleted(self, candidate_id: str) -> bool:
        return self._record(candidate_id) is not None or self._candidates.is_deletion_marked(
            candidate_id
        )

    def deletion_status(self, candidate_id: str) -> CandidateDeletionView:
        record = self._record(candidate_id)
        if record is None:
            marker_time = self._candidates.deletion_marker_time(candidate_id)
            if marker_time is not None:
                return CandidateDeletionView(
                    candidate_id=candidate_id,
                    status="failed",
                    deleted_rows={},
                    deleted_paths=(),
                    error_code="deletion_interrupted_before_receipt",
                    requested_at=marker_time,
                    completed_at=None,
                )
            raise CandidateDeletionError(
                "deletion_not_found", "Candidate deletion receipt was not found."
            )
        return self._view(record)

    def purge_expired_browser_sessions(
        self, candidate_id: str, *, now: datetime | None = None
    ) -> int:
        with self._candidates.lifecycle_write(candidate_id):
            return self._purge_expired_browser_sessions(candidate_id, now=now)

    def _purge_expired_browser_sessions(
        self, candidate_id: str, *, now: datetime | None = None
    ) -> int:
        self._candidates.get_config(candidate_id)
        current = now or datetime.now(UTC)
        quarantines: list[tuple[Path, Path]] = []
        try:
            with self._sessions.begin() as session:
                settings = session.scalar(
                    select(CandidateSettingsRecord).where(
                        CandidateSettingsRecord.candidate_id == candidate_id
                    )
                )
                retention_days = settings.browser_session_retention_days if settings else 30
                cutoff = current - timedelta(days=retention_days)
                expired = session.scalars(
                    select(BrowserSession).where(
                        BrowserSession.candidate_id == candidate_id,
                        or_(
                            BrowserSession.status.in_(
                                ("confirmed", "ready", "synthetic_ready", "cancelled", "expired")
                            ),
                            and_(
                                BrowserSession.status.in_(
                                    ("human_action_required", "human_takeover_opened")
                                ),
                                exists(
                                    select(HumanAction.id).where(
                                        HumanAction.candidate_id == candidate_id,
                                        HumanAction.browser_session_id == BrowserSession.id,
                                        HumanAction.status == "pending",
                                        HumanAction.expires_at.is_not(None),
                                        HumanAction.expires_at <= current,
                                    )
                                ),
                            ),
                        ),
                        BrowserSession.updated_at < cutoff,
                    )
                ).all()
                expired_session_ids = {item.id for item in expired}
                expired_actions = session.scalars(
                    select(HumanAction).where(
                        HumanAction.candidate_id == candidate_id,
                        HumanAction.status == "pending",
                        HumanAction.expires_at.is_not(None),
                        HumanAction.expires_at <= current,
                    )
                ).all()
                for action in expired_actions:
                    action.status = "cancelled"
                    action.completed_at = current
                    browser_session = (
                        session.get(BrowserSession, action.browser_session_id)
                        if action.browser_session_id is not None
                        else None
                    )
                    if (
                        browser_session is not None
                        and browser_session.candidate_id == candidate_id
                        and browser_session.application_id == action.application_id
                        and browser_session.id not in expired_session_ids
                    ):
                        browser_session.status = "expired"
                    application = session.get(Application, action.application_id)
                    profile_deleted = (
                        browser_session is not None and browser_session.id in expired_session_ids
                    )
                    if (
                        application is not None
                        and application.candidate_id == candidate_id
                        and application.state is ApplicationState.HUMAN_ACTION_REQUIRED
                    ):
                        session.add(
                            ApplicationEvent(
                                candidate_id=candidate_id,
                                application_id=application.id,
                                idempotency_key=f"expiry:human-action:{action.id}",
                                event_type="HUMAN_ACTION_EXPIRED",
                                from_state=application.state,
                                to_state=ApplicationState.FORM_FILLING,
                                payload={
                                    "action_id": str(action.id),
                                    "browser_session_id": (
                                        str(action.browser_session_id)
                                        if action.browser_session_id is not None
                                        else None
                                    ),
                                    "browser_profile_deleted": profile_deleted,
                                    "session_metadata_retained": True,
                                },
                            )
                        )
                        application.state = ApplicationState.FORM_FILLING
                for browser_session in expired:
                    quarantine_pair = self._quarantine_browser_session_tree(
                        candidate_id, browser_session.id
                    )
                    if quarantine_pair is not None:
                        quarantines.append(quarantine_pair)
                    actions = session.scalars(
                        select(HumanAction).where(
                            HumanAction.candidate_id == candidate_id,
                            HumanAction.browser_session_id == browser_session.id,
                        )
                    ).all()
                    for action in actions:
                        action.screenshot_uri = None
                    browser_session.external_session_ref = None
                    browser_session.status = "retained_metadata"
                if expired or expired_actions:
                    self._append_audit(session, candidate_id, "candidate.browser_retention_applied")
                expired_count = len(expired)
        except Exception:
            for quarantine_path, live in reversed(quarantines):
                if quarantine_path.is_dir() and not live.exists():
                    quarantine_path.rename(live)
            raise
        for quarantine_path, _live in quarantines:
            self._finalize_browser_session_quarantine(quarantine_path)
        self._finalize_committed_browser_quarantines(candidate_id)
        return expired_count

    def _quarantine_browser_session_tree(
        self, candidate_id: str, session_id: Any
    ) -> tuple[Path, Path] | None:
        sessions_root = self._runtime_root / "candidates" / candidate_id / "sessions"
        if not sessions_root.exists():
            return None
        if (
            sessions_root.is_symlink()
            or not sessions_root.is_dir()
            or sessions_root.resolve()
            != (self._runtime_root / "candidates" / candidate_id / "sessions").absolute()
        ):
            raise CandidateDeletionError(
                "unsafe_candidate_path", "Browser session retention path is unsafe."
            )
        target = sessions_root / str(session_id)
        quarantine = sessions_root / f".retaining-{session_id}"
        if target.exists() and quarantine.exists():
            raise CandidateDeletionError(
                "unsafe_candidate_path", "Browser session retention quarantine conflicts."
            )
        if quarantine.exists():
            if quarantine.is_symlink() or not quarantine.is_dir():
                raise CandidateDeletionError(
                    "unsafe_candidate_path", "Browser session quarantine is unsafe."
                )
            return quarantine, target
        if not target.exists():
            return None
        if (
            target.is_symlink()
            or not target.is_dir()
            or target.resolve().parent != sessions_root.resolve()
        ):
            raise CandidateDeletionError(
                "unsafe_candidate_path", "Browser session retention tree is unsafe."
            )
        self._reject_unsafe_tree(target)
        target.rename(quarantine)
        return quarantine, target

    def _finalize_committed_browser_quarantines(self, candidate_id: str) -> None:
        sessions_root = self._runtime_root / "candidates" / candidate_id / "sessions"
        if not sessions_root.is_dir() or sessions_root.is_symlink():
            return
        with self._sessions() as session:
            retained_ids = set(
                session.scalars(
                    select(BrowserSession.id).where(
                        BrowserSession.candidate_id == candidate_id,
                        BrowserSession.status == "retained_metadata",
                    )
                )
            )
        for session_id in retained_ids:
            quarantine = sessions_root / f".retaining-{session_id}"
            if quarantine.exists() or quarantine.is_symlink():
                self._finalize_browser_session_quarantine(quarantine)

    def _finalize_browser_session_quarantine(self, quarantine: Path) -> None:
        if quarantine.is_symlink() or not quarantine.is_dir():
            raise CandidateDeletionError(
                "unsafe_candidate_path", "Browser session quarantine is unsafe."
            )
        self._reject_unsafe_tree(quarantine)
        shutil.rmtree(quarantine)

    @staticmethod
    def _reject_unsafe_tree(target: Path) -> None:
        for path in target.rglob("*"):
            metadata = path.lstat()
            if path.is_symlink():
                raise CandidateDeletionError(
                    "unsafe_candidate_path", "Candidate data tree contains a symlink."
                )
            if path.is_dir():
                continue
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise CandidateDeletionError(
                    "unsafe_candidate_path", "Candidate data tree contains an unsafe file."
                )

    @staticmethod
    def _validate_replay(record: CandidateDeletionRecord, request_sha256: str) -> None:
        if record.request_sha256 != request_sha256:
            raise CandidateDeletionError(
                "idempotency_conflict", "Candidate deletion request conflicts with its receipt."
            )

    def _ensure_deletion_key_available(
        self, candidate_id: str, idempotency_key_sha256: str
    ) -> None:
        with self._sessions() as session:
            owner = session.scalar(
                select(CandidateDeletionRecord).where(
                    CandidateDeletionRecord.idempotency_key_sha256 == idempotency_key_sha256,
                    CandidateDeletionRecord.candidate_id != candidate_id,
                )
            )
            if owner is not None:
                raise CandidateDeletionError(
                    "idempotency_conflict",
                    "Candidate deletion key is already bound to another request.",
                )

    def _append_audit(
        self,
        session: Session,
        candidate_id: str,
        event_type: str,
        *,
        pseudonymize: bool = False,
    ) -> None:
        subject_id = self._audit_subject(candidate_id) if pseudonymize else candidate_id
        previous = session.scalar(
            select(AdministrativeAuditRecord)
            .where(AdministrativeAuditRecord.candidate_id == subject_id)
            .order_by(AdministrativeAuditRecord.occurred_at.desc())
            .limit(1)
        )
        occurred_at = datetime.now(UTC)
        previous_hash = previous.event_hash if previous else None
        content = canonical_json_bytes(
            {
                "candidate_id": subject_id,
                "actor_id": "local-user",
                "event_type": event_type,
                "details": {},
                "previous_hash": previous_hash,
                "occurred_at": occurred_at,
            }
        )
        session.add(
            AdministrativeAuditRecord(
                candidate_id=subject_id,
                actor_id="local-user",
                event_type=event_type,
                details={},
                previous_hash=previous_hash,
                event_hash=hashlib.sha256(content).hexdigest(),
                occurred_at=occurred_at,
            )
        )

    def _audit_subject(self, candidate_id: str) -> str:
        root = self._runtime_root
        if root.is_symlink():
            raise CandidateDeletionError(
                "unsafe_candidate_path", "Runtime root is unsafe for deletion auditing."
            )
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        key_path = root / ".deletion_audit_key"
        lock_path = root / ".deletion_audit_key.lock"
        if key_path.is_symlink():
            raise CandidateDeletionError(
                "unsafe_candidate_path", "Deletion audit key path is unsafe."
            )
        if lock_path.is_symlink():
            raise CandidateDeletionError(
                "unsafe_candidate_path", "Deletion audit lock path is unsafe."
            )
        lock_descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
        )
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            try:
                descriptor = os.open(
                    key_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                    0o600,
                )
            except FileExistsError:
                pass
            else:
                try:
                    os.write(descriptor, os.urandom(32))
                finally:
                    os.close(descriptor)
            descriptor = os.open(key_path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                key = os.read(descriptor, 33)
            finally:
                os.close(descriptor)
        finally:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            os.close(lock_descriptor)
        if len(key) != 32:
            raise CandidateDeletionError(
                "candidate_deletion_failed", "Deletion audit key is invalid."
            )
        digest = hmac.new(key, candidate_id.encode(), hashlib.sha256).hexdigest()
        return f"deleted_{digest[:56]}"

    @staticmethod
    def _view(record: CandidateDeletionRecord) -> CandidateDeletionView:
        requested_at = record.requested_at
        completed_at = record.completed_at
        return CandidateDeletionView(
            candidate_id=record.candidate_id,
            status=record.status,
            deleted_rows={key: int(value) for key, value in record.deleted_rows.items()},
            deleted_paths=tuple(record.deleted_paths),
            error_code=record.error_code,
            requested_at=(
                requested_at
                if requested_at.tzinfo is not None
                else requested_at.replace(tzinfo=UTC)
            ),
            completed_at=(
                completed_at
                if completed_at is None or completed_at.tzinfo is not None
                else completed_at.replace(tzinfo=UTC)
            ),
        )
