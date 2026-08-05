from __future__ import annotations

import json
import secrets
import time
from datetime import UTC, datetime
from typing import NoReturn

from redis import Redis

from app.candidates.service import CandidateService
from app.core.settings import Settings
from app.db import build_engine, build_session_factory
from app.discovery.providers import ProviderFeedClient
from app.discovery.scheduled import ScheduledDiscoveryService
from app.job_service import JobService
from app.tasks import TaskLeaseLostError, TaskQueue, TaskView


def run_scheduler_once(
    queue: TaskQueue,
    candidates: CandidateService,
    *,
    now: datetime | None = None,
    discovery: ScheduledDiscoveryService | None = None,
) -> tuple[TaskView, ...]:
    current = now or datetime.now(UTC)
    bucket = current.strftime("%Y%m%dT%H") + f"{(current.minute // 15) * 15:02d}"
    readiness = tuple(
        queue.enqueue(
            candidate_id=candidate.candidate_id,
            kind="candidate_readiness_check",
            idempotency_key=f"readiness:{bucket}",
            payload={"profile_version": candidate.profile_version},
            scheduled_for=current,
        )
        for candidate in candidates.list_candidates()
    )
    return (*readiness, *(discovery.enqueue_due(queue, now=current) if discovery else ()))


def run_worker_once(
    queue: TaskQueue,
    candidates: CandidateService,
    *,
    worker_id: str,
    now: datetime | None = None,
    discovery: ScheduledDiscoveryService | None = None,
) -> TaskView | None:
    task = queue.claim(worker_id=worker_id, now=now)
    if task is None:
        return None
    try:
        if task.kind == "discover_source" and discovery is not None:
            discovery.execute_task(task, now=now)
        elif task.kind != "candidate_readiness_check":
            raise ValueError(f"unsupported workflow task kind: {task.kind}")
        else:
            candidates.readiness(task.candidate_id)
    except Exception as exc:
        try:
            return queue.fail(task.task_id, worker_id=worker_id, error=type(exc).__name__)
        except TaskLeaseLostError:
            return queue.get(task.task_id)
    try:
        return queue.complete(task.task_id, worker_id=worker_id)
    except TaskLeaseLostError:
        return queue.get(task.task_id)


def run_process(role: str) -> NoReturn:
    """Run a durable local scheduler or worker with Redis health publication."""
    settings = Settings.from_environment()
    sessions = build_session_factory(build_engine(settings.database_url))
    queue = TaskQueue(sessions)
    candidates = CandidateService(settings.candidates_root)
    discovery = ScheduledDiscoveryService(
        sessions,
        candidates,
        JobService(sessions, candidates),
        ProviderFeedClient(),
    )
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    worker_id = f"{role}-{secrets.token_hex(6)}"
    channel = f"careeros:{role}:heartbeat"
    while True:
        if role == "scheduler":
            processed = len(run_scheduler_once(queue, candidates, discovery=discovery))
        elif role == "worker":
            processed = int(
                run_worker_once(queue, candidates, worker_id=worker_id, discovery=discovery)
                is not None
            )
        else:
            raise ValueError(f"unsupported runtime role: {role}")
        redis.set(
            channel,
            json.dumps(
                {"role": role, "status": "ready", "processed": processed, "worker_id": worker_id}
            ),
            ex=90,
        )
        time.sleep(15 if role == "worker" else 30)
