from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.models import WorkflowTask


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
        if not candidate_id or not kind or not idempotency_key:
            raise ValueError("candidate_id, kind, and idempotency_key are required")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        with self._sessions.begin() as session:
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
    ) -> TaskView | None:
        current = now or datetime.now(UTC)
        expired = current - lease
        with self._sessions.begin() as session:
            task = session.scalar(
                select(WorkflowTask)
                .where(
                    WorkflowTask.attempts < WorkflowTask.max_attempts,
                    WorkflowTask.scheduled_for <= current,
                    or_(
                        WorkflowTask.status == "pending",
                        ((WorkflowTask.status == "running") & (WorkflowTask.locked_at < expired)),
                    ),
                )
                .order_by(WorkflowTask.scheduled_for, WorkflowTask.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if task is None:
                return None
            task.status = "running"
            task.locked_by = worker_id
            task.locked_at = current
            task.attempts += 1
            session.flush()
            return self._view(task)

    def complete(self, task_id: UUID, *, worker_id: str) -> TaskView:
        with self._sessions.begin() as session:
            task = self._owned_running_task(session, task_id, worker_id)
            task.status = "completed"
            task.completed_at = datetime.now(UTC)
            task.locked_by = None
            task.locked_at = None
            return self._view(task)

    def get(self, task_id: UUID) -> TaskView:
        with self._sessions() as session:
            task = session.get(WorkflowTask, task_id)
            if task is None:
                raise ValueError("workflow task not found")
            return self._view(task)

    def fail(
        self,
        task_id: UUID,
        *,
        worker_id: str,
        error: str,
        retry_delay: timedelta = timedelta(seconds=30),
    ) -> TaskView:
        with self._sessions.begin() as session:
            task = self._owned_running_task(session, task_id, worker_id)
            task.last_error = error[:1000]
            task.locked_by = None
            task.locked_at = None
            if task.attempts >= task.max_attempts:
                task.status = "failed"
            else:
                task.status = "pending"
                task.scheduled_for = datetime.now(UTC) + retry_delay
            return self._view(task)

    @staticmethod
    def _owned_running_task(session: Session, task_id: UUID, worker_id: str) -> WorkflowTask:
        task = session.get(WorkflowTask, task_id)
        if task is None:
            raise ValueError("workflow task not found")
        if task.status != "running" or task.locked_by != worker_id:
            raise TaskLeaseLostError("workflow task is not leased by this worker")
        return task

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
        )
