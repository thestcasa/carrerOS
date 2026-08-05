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
from app.tasks import TaskQueue, TaskView


def run_scheduler_once(
    queue: TaskQueue,
    candidates: CandidateService,
    *,
    now: datetime | None = None,
) -> tuple[TaskView, ...]:
    current = now or datetime.now(UTC)
    bucket = current.strftime("%Y%m%dT%H") + f"{(current.minute // 15) * 15:02d}"
    return tuple(
        queue.enqueue(
            candidate_id=candidate.candidate_id,
            kind="candidate_readiness_check",
            idempotency_key=f"readiness:{bucket}",
            payload={"profile_version": candidate.profile_version},
            scheduled_for=current,
        )
        for candidate in candidates.list_candidates()
    )


def run_worker_once(
    queue: TaskQueue,
    candidates: CandidateService,
    *,
    worker_id: str,
    now: datetime | None = None,
) -> TaskView | None:
    task = queue.claim(worker_id=worker_id, now=now)
    if task is None:
        return None
    try:
        if task.kind != "candidate_readiness_check":
            raise ValueError(f"unsupported workflow task kind: {task.kind}")
        candidates.readiness(task.candidate_id)
    except Exception as exc:
        return queue.fail(task.task_id, worker_id=worker_id, error=type(exc).__name__)
    return queue.complete(task.task_id, worker_id=worker_id)


def run_process(role: str) -> NoReturn:
    """Run a durable local scheduler or worker with Redis health publication."""
    settings = Settings.from_environment()
    queue = TaskQueue(build_session_factory(build_engine(settings.database_url)))
    candidates = CandidateService(settings.candidates_root)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    worker_id = f"{role}-{secrets.token_hex(6)}"
    channel = f"careeros:{role}:heartbeat"
    while True:
        if role == "scheduler":
            processed = len(run_scheduler_once(queue, candidates))
        elif role == "worker":
            processed = int(run_worker_once(queue, candidates, worker_id=worker_id) is not None)
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
