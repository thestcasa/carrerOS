from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.lifecycle import CandidateLifecycleService
from app.candidates.service import CandidateService
from app.db import build_session_factory
from app.discovery.scheduled import ScheduledDiscoveryService
from app.domain.models import Base, WorkflowTask
from app.runtime import run_scheduler_once, run_worker_once
from app.tasks import TaskQueue, TaskView


def _queue() -> tuple[TaskQueue, sessionmaker[Session]]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    return TaskQueue(sessions), sessions


def test_queue_is_idempotent_leased_and_recovers_expired_work() -> None:
    queue, _sessions = _queue()
    now = datetime(2026, 8, 5, 10, tzinfo=UTC)
    first = queue.enqueue(
        candidate_id="candidate_alpha",
        kind="candidate_readiness_check",
        idempotency_key="readiness-1",
        scheduled_for=now,
    )
    assert (
        queue.enqueue(
            candidate_id="candidate_alpha",
            kind="candidate_readiness_check",
            idempotency_key="readiness-1",
            scheduled_for=now,
        ).task_id
        == first.task_id
    )
    with pytest.raises(ValueError, match="different task"):
        queue.enqueue(
            candidate_id="candidate_alpha",
            kind="other",
            idempotency_key="readiness-1",
        )

    claimed = queue.claim(worker_id="worker-a", now=now)
    assert claimed is not None and claimed.attempts == 1
    assert queue.claim(worker_id="worker-b", now=now) is None
    recovered = queue.claim(worker_id="worker-b", now=now + timedelta(minutes=6))
    assert recovered is not None and recovered.task_id == first.task_id
    assert queue.complete(recovered.task_id, worker_id="worker-b").status == "completed"


def test_scheduler_and_worker_process_candidate_readiness_durably(
    copied_candidates_root: Path,
) -> None:
    queue, sessions = _queue()
    candidates = CandidateService(copied_candidates_root)
    now = datetime(2026, 8, 5, 10, tzinfo=UTC)
    scheduled = run_scheduler_once(queue, candidates, now=now)
    replay = run_scheduler_once(queue, candidates, now=now)

    assert len(scheduled) == len(replay) == 1
    assert scheduled[0].task_id == replay[0].task_id
    completed = run_worker_once(queue, candidates, worker_id="worker-a", now=now)
    assert completed is not None and completed.status == "completed"
    with sessions() as session:
        assert session.scalar(select(func.count(WorkflowTask.id))) == 1


def test_worker_does_not_mutate_or_crash_after_task_lease_is_reclaimed(
    copied_candidates_root: Path,
) -> None:
    queue, _sessions = _queue()
    candidates = CandidateService(copied_candidates_root)
    now = datetime(2026, 8, 5, 10, tzinfo=UTC)
    queued = queue.enqueue(
        candidate_id="example_candidate",
        kind="discover_source",
        idempotency_key="discovery-takeover",
        payload={"source_id": "fixture", "cadence_bucket": "fixture"},
        scheduled_for=now,
    )

    class ReclaimingDiscovery:
        def execute_task(self, task: TaskView, *, now: datetime | None = None) -> None:
            assert task.task_id == queued.task_id
            assert now is not None
            reclaimed = queue.claim(worker_id="worker-new", now=now + timedelta(minutes=6))
            assert reclaimed is not None and reclaimed.task_id == task.task_id
            raise ValueError("stale execution stopped")

    current = run_worker_once(
        queue,
        candidates,
        worker_id="worker-old",
        now=now,
        discovery=cast(ScheduledDiscoveryService, ReclaimingDiscovery()),
    )

    assert current is not None
    assert current.status == "running"
    assert current.locked_by == "worker-new"
    assert current.attempts == 2
    assert current.last_error is None


def test_scheduler_and_worker_run_daily_retention_durably(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    queue, sessions = _queue()
    candidates = CandidateService(copied_candidates_root)
    lifecycle = CandidateLifecycleService(sessions, candidates, tmp_path / "runtime")
    now = datetime(2026, 8, 5, 10, tzinfo=UTC)

    scheduled = run_scheduler_once(queue, candidates, now=now, lifecycle=lifecycle)
    replay = run_scheduler_once(queue, candidates, now=now, lifecycle=lifecycle)

    assert len(scheduled) == len(replay) == 2
    assert {item.kind for item in scheduled} == {
        "candidate_readiness_check",
        "candidate_retention_sweep",
    }
    first = run_worker_once(
        queue, candidates, worker_id="retention-worker", now=now, lifecycle=lifecycle
    )
    second = run_worker_once(
        queue, candidates, worker_id="retention-worker", now=now, lifecycle=lifecycle
    )
    assert first is not None and first.status == "completed"
    assert second is not None and second.status == "completed"
