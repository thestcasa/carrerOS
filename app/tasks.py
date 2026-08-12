from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.models import CandidateDeletionRecord, WorkflowTask


class TaskLeaseLostError(ValueError):
    """The caller no longer owns the durable task lease and must not mutate it."""


class TaskContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TaskView(TaskContract):
    task_id: UUID
    candidate_id: str
    kind: str
    status: str
    payload: dict[str, object]
    attempts: int
    max_attempts: int
    scheduled_for: datetime
    locked_by: str | None
    last_error: str | None
    last_error_category: str | None = None
    last_error_retryable: bool | None = None
    attempt_history: list[dict[str, object]] = Field(default_factory=list)


class TaskQueue:
    """Small SQL-backed queue used by the local worker and scheduler processes."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    def enqueue(
        self,
        *,
        candidate_id: str,
        kind: str,
        idempotency_key: str,
        payload: dict[str, object] | None = None,
        scheduled_for: datetime | None = None,
        max_attempts: int = 3,
    ) -> TaskView:
        try:
            with self._sessions.begin() as session:
                return self.enqueue_in_session(
                    session,
                    candidate_id=candidate_id,
                    kind=kind,
                    idempotency_key=idempotency_key,
                    payload=payload,
                    scheduled_for=scheduled_for,
                    max_attempts=max_attempts,
                )
        except IntegrityError as exc:
            if self._deleted_candidate_integrity(exc):
                raise TaskLeaseLostError("candidate lifecycle is no longer active") from exc
            raise

    def enqueue_in_session(
        self,
        session: Session,
        *,
        candidate_id: str,
        kind: str,
        idempotency_key: str,
        payload: dict[str, object] | None = None,
        scheduled_for: datetime | None = None,
        max_attempts: int = 3,
    ) -> TaskView:
        """Enqueue within a caller-owned transaction for atomic state transitions."""

        if not candidate_id or not kind or not idempotency_key:
            raise ValueError("candidate_id, kind, and idempotency_key are required")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if session.get(CandidateDeletionRecord, candidate_id) is not None:
            raise TaskLeaseLostError("candidate lifecycle is no longer active")
        existing = session.scalar(
            select(WorkflowTask).where(
                WorkflowTask.candidate_id == candidate_id,
                WorkflowTask.idempotency_key == idempotency_key,
            )
        )
        expected_payload = payload or {}
        if existing is not None:
            if existing.kind != kind or existing.payload != expected_payload:
                raise ValueError("idempotency key was used for a different task")
            return self._view(existing)
        task = WorkflowTask(
            candidate_id=candidate_id,
            kind=kind,
            idempotency_key=idempotency_key,
            payload=expected_payload,
            scheduled_for=scheduled_for or datetime.now(UTC),
            max_attempts=max_attempts,
        )
        session.add(task)
        session.flush()
        return self._view(task)

    def claim(
        self,
        *,
        worker_id: str,
        now: datetime | None = None,
        lease: timedelta = timedelta(minutes=5),
        allowed_kinds: frozenset[str] | None = None,
    ) -> TaskView | None:
        current = now or datetime.now(UTC)
        expired = current - lease
        try:
            with self._sessions.begin() as session:
                statement = (
                    select(WorkflowTask)
                    .where(
                        WorkflowTask.attempts < WorkflowTask.max_attempts,
                        WorkflowTask.scheduled_for <= current,
                        ~exists(
                            select(CandidateDeletionRecord.candidate_id).where(
                                CandidateDeletionRecord.candidate_id == WorkflowTask.candidate_id
                            )
                        ),
                        or_(
                            WorkflowTask.status == "pending",
                            (
                                (WorkflowTask.status == "running")
                                & (WorkflowTask.locked_at < expired)
                            ),
                        ),
                    )
                    .order_by(WorkflowTask.scheduled_for, WorkflowTask.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if allowed_kinds is not None:
                    statement = statement.where(WorkflowTask.kind.in_(allowed_kinds))
                task = session.scalar(statement)
                if task is None:
                    return None
                if task.status == "running":
                    task.attempt_history = [
                        *(task.attempt_history or []),
                        {
                            "event": "lease_recovered",
                            "attempt": task.attempts,
                            "prior_worker_id": task.locked_by,
                            "prior_locked_at": self._timestamp(task.locked_at),
                            "recovered_at": self._timestamp(current),
                        },
                    ]
                task.status = "running"
                task.locked_by = worker_id
                task.locked_at = current
                task.attempts += 1
                session.flush()
                return self._view(task)
        except IntegrityError as exc:
            if self._deleted_candidate_integrity(exc):
                return None
            raise

    def complete(self, task_id: UUID, *, worker_id: str, now: datetime | None = None) -> TaskView:
        try:
            with self._sessions.begin() as session:
                return self.complete_in_session(session, task_id, worker_id=worker_id, now=now)
        except IntegrityError as exc:
            if self._deleted_candidate_integrity(exc):
                raise TaskLeaseLostError("candidate lifecycle is no longer active") from exc
            raise

    def complete_in_session(
        self,
        session: Session,
        task_id: UUID,
        *,
        worker_id: str,
        now: datetime | None = None,
        expected_attempt: int | None = None,
    ) -> TaskView:
        """Complete an exactly-owned lease in a caller-owned transaction."""

        task = self._owned_running_task(
            session, task_id, worker_id, expected_attempt=expected_attempt
        )
        task.status = "completed"
        task.completed_at = now or datetime.now(UTC)
        task.locked_by = None
        task.locked_at = None
        session.flush()
        return self._view(task)

    def get(self, task_id: UUID) -> TaskView | None:
        with self._sessions() as session:
            task = session.get(WorkflowTask, task_id)
            if task is None:
                return None
            return self._view(task)

    def fail(
        self,
        task_id: UUID,
        *,
        worker_id: str,
        category: str | None = None,
        retryable: bool = True,
        safe_details: dict[str, object] | None = None,
        error: str | None = None,
        retry_delay: timedelta = timedelta(seconds=30),
        now: datetime | None = None,
    ) -> TaskView:
        try:
            with self._sessions.begin() as session:
                return self.fail_in_session(
                    session,
                    task_id,
                    worker_id=worker_id,
                    category=category,
                    retryable=retryable,
                    safe_details=safe_details,
                    error=error,
                    retry_delay=retry_delay,
                    now=now,
                )
        except IntegrityError as exc:
            if self._deleted_candidate_integrity(exc):
                raise TaskLeaseLostError("candidate lifecycle is no longer active") from exc
            raise

    def fail_in_session(
        self,
        session: Session,
        task_id: UUID,
        *,
        worker_id: str,
        category: str | None = None,
        retryable: bool = True,
        safe_details: dict[str, object] | None = None,
        error: str | None = None,
        retry_delay: timedelta = timedelta(seconds=30),
        now: datetime | None = None,
        expected_attempt: int | None = None,
    ) -> TaskView:
        """Record a categorized failure in a caller-owned transaction."""

        stable_category = category or error
        if not stable_category:
            raise ValueError("failure category is required")
        if category is not None and error is not None and category != error:
            raise ValueError("category and legacy error must match")
        current = now or datetime.now(UTC)
        task = self._owned_running_task(
            session, task_id, worker_id, expected_attempt=expected_attempt
        )
        task.last_error = stable_category[:1000]
        task.last_error_category = stable_category[:64]
        task.last_error_retryable = retryable
        task.attempt_history = [
            *(task.attempt_history or []),
            {
                "event": "attempt_failed",
                "attempt": task.attempts,
                "worker_id": worker_id,
                "category": stable_category[:64],
                "retryable": retryable,
                "details": safe_details or {},
                "failed_at": self._timestamp(current),
            },
        ]
        task.locked_by = None
        task.locked_at = None
        if retryable and task.attempts < task.max_attempts:
            task.status = "pending"
            task.scheduled_for = current + retry_delay
        else:
            task.status = "failed"
        session.flush()
        return self._view(task)

    @staticmethod
    def _deleted_candidate_integrity(exc: IntegrityError) -> bool:
        return "candidate is deleted" in str(exc).casefold()

    def assert_lease_in_session(
        self,
        session: Session,
        task_id: UUID,
        *,
        worker_id: str,
        expected_attempt: int,
    ) -> None:
        """Lock and validate an exact attempt before caller-owned side effects."""

        self._owned_running_task(
            session,
            task_id,
            worker_id,
            expected_attempt=expected_attempt,
        )

    @staticmethod
    def _owned_running_task(
        session: Session,
        task_id: UUID,
        worker_id: str,
        *,
        expected_attempt: int | None = None,
    ) -> WorkflowTask:
        task = session.scalar(
            select(WorkflowTask).where(WorkflowTask.id == task_id).with_for_update()
        )
        if task is None:
            raise TaskLeaseLostError("workflow task no longer exists")
        if task.status != "running" or task.locked_by != worker_id:
            raise TaskLeaseLostError("workflow task is not leased by this worker")
        if expected_attempt is not None and task.attempts != expected_attempt:
            raise TaskLeaseLostError("workflow task lease generation has changed")
        return task

    @staticmethod
    def _timestamp(value: datetime | None) -> str | None:
        if value is None:
            return None
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return normalized.astimezone(UTC).isoformat()

    @staticmethod
    def _view(task: WorkflowTask) -> TaskView:
        return TaskView(
            task_id=task.id,
            candidate_id=task.candidate_id,
            kind=task.kind,
            status=task.status,
            payload=task.payload,
            attempts=task.attempts,
            max_attempts=task.max_attempts,
            scheduled_for=task.scheduled_for,
            locked_by=task.locked_by,
            last_error=task.last_error,
            last_error_category=task.last_error_category,
            last_error_retryable=task.last_error_retryable,
            attempt_history=task.attempt_history or [],
        )
