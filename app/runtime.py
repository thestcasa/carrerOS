from __future__ import annotations

import json
import secrets
import threading
import time
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from typing import NoReturn

from redis import Redis

from app.applications.service import ApplicationService
from app.auth.lifecycle import CandidateLifecycleService
from app.browser.fixture_server import SyntheticATSHandler
from app.browser.playwright_worker import RestrictedPlaywrightWorker
from app.candidates.service import CandidateService
from app.core.settings import Settings
from app.db import build_engine, build_session_factory
from app.discovery.providers import ProviderFeedClient
from app.discovery.scheduled import ScheduledDiscoveryService
from app.discovery.verification import ProviderJobSourceVerifier
from app.job_service import JobService
from app.submission import ControlledSubmissionExecutor, GreenhousePlaywrightExecutor
from app.tasks import TaskLeaseLostError, TaskQueue, TaskView


def run_scheduler_once(
    queue: TaskQueue,
    candidates: CandidateService,
    *,
    now: datetime | None = None,
    discovery: ScheduledDiscoveryService | None = None,
    lifecycle: CandidateLifecycleService | None = None,
    applications: ApplicationService | None = None,
) -> tuple[TaskView, ...]:
    current = now or datetime.now(UTC)
    bucket = current.strftime("%Y%m%dT%H") + f"{(current.minute // 15) * 15:02d}"
    readiness: list[TaskView] = []
    retention: list[TaskView] = []
    for candidate in candidates.list_candidates():
        try:
            readiness.append(
                queue.enqueue(
                    candidate_id=candidate.candidate_id,
                    kind="candidate_readiness_check",
                    idempotency_key=(
                        f"readiness:{bucket}:profile:{candidate.profile_version or 'invalid'}"
                    ),
                    payload={"profile_version": candidate.profile_version},
                    scheduled_for=current,
                )
            )
            if lifecycle is not None:
                retention.append(
                    queue.enqueue(
                        candidate_id=candidate.candidate_id,
                        kind="candidate_retention_sweep",
                        idempotency_key=f"retention:{bucket}",
                        payload={},
                        scheduled_for=current,
                    )
                )
            if applications is not None:
                applications.enqueue_autonomous_controlled_submissions(candidate.candidate_id)
        except TaskLeaseLostError:
            continue
    return (
        *readiness,
        *retention,
        *(discovery.enqueue_due(queue, now=current) if discovery else ()),
    )


def run_worker_once(
    queue: TaskQueue,
    candidates: CandidateService,
    *,
    worker_id: str,
    now: datetime | None = None,
    discovery: ScheduledDiscoveryService | None = None,
    lifecycle: CandidateLifecycleService | None = None,
) -> TaskView | None:
    task = queue.claim(
        worker_id=worker_id,
        now=now,
        allowed_kinds=frozenset(
            {"candidate_readiness_check", "candidate_retention_sweep", "discover_source"}
        ),
    )
    if task is None:
        return None
    try:
        if task.kind == "discover_source" and discovery is not None:
            discovery.execute_task(task, now=now)
        elif task.kind == "candidate_retention_sweep" and lifecycle is not None:
            lifecycle.purge_expired_browser_sessions(task.candidate_id, now=now)
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


def run_browser_worker_once(
    queue: TaskQueue,
    applications: ApplicationService,
    executor: RestrictedPlaywrightWorker,
    *,
    worker_id: str,
    fixture_base_url: str,
    now: datetime | None = None,
) -> TaskView | None:
    task = queue.claim(
        worker_id=worker_id,
        now=now,
        allowed_kinds=frozenset({"browser_dry_run"}),
    )
    if task is None:
        return None
    return applications.execute_browser_task(
        queue,
        task,
        worker_id=worker_id,
        executor=executor,
        fixture_base_url=fixture_base_url,
        now=now,
    )


def run_controlled_submission_worker_once(
    queue: TaskQueue,
    applications: ApplicationService,
    executor: ControlledSubmissionExecutor,
    *,
    worker_id: str,
    now: datetime | None = None,
) -> TaskView | None:
    task = queue.claim(
        worker_id=worker_id,
        now=now,
        allowed_kinds=frozenset({"controlled_submission"}),
    )
    if task is None:
        return None
    return applications.execute_controlled_submission_task(
        queue,
        task,
        worker_id=worker_id,
        executor=executor,
        now=now,
    )


def run_process(role: str) -> NoReturn:
    """Run a durable local scheduler or worker with Redis health publication."""
    settings = Settings.from_environment()
    sessions = build_session_factory(build_engine(settings.database_url))
    queue = TaskQueue(sessions)
    candidates = CandidateService(settings.candidates_root, settings.candidate_fixtures_root)
    source_verifier = ProviderJobSourceVerifier()
    discovery = ScheduledDiscoveryService(
        sessions,
        candidates,
        JobService(sessions, candidates, source_verifier),
        ProviderFeedClient(),
    )
    lifecycle = CandidateLifecycleService(sessions, candidates, settings.runtime_root)
    applications = ApplicationService(
        sessions,
        candidates,
        settings.runtime_root,
        source_verifier=source_verifier,
        controlled_submission_enabled=settings.controlled_submission_enabled,
    )
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    worker_id = f"{role}-{secrets.token_hex(6)}"
    channel = f"careeros:{role}:heartbeat"
    fixture_server: ThreadingHTTPServer | None = None
    fixture_thread: threading.Thread | None = None
    fixture_base_url = "http://127.0.0.1:8090/application"
    browser_executor: RestrictedPlaywrightWorker | None = None
    controlled_executor: GreenhousePlaywrightExecutor | None = None
    if role == "browser-worker":
        fixture_server = ThreadingHTTPServer(("127.0.0.1", 8090), SyntheticATSHandler)
        fixture_thread = threading.Thread(target=fixture_server.serve_forever, daemon=True)
        fixture_thread.start()
        browser_executor = RestrictedPlaywrightWorker(
            settings.runtime_root,
            frozenset(
                f"{fixture_base_url}?challenge={challenge}"
                for challenge in ("none", "captcha", "otp")
            ),
        )
    elif role == "controlled-submission-worker":
        if not settings.controlled_submission_enabled:
            raise ValueError("controlled submission worker requires explicit runtime enablement")
        controlled_executor = GreenhousePlaywrightExecutor(
            settings.runtime_root,
            enabled=True,
        )
    try:
        while True:
            if role == "scheduler":
                processed = len(
                    run_scheduler_once(
                        queue,
                        candidates,
                        discovery=discovery,
                        lifecycle=lifecycle,
                        applications=applications,
                    )
                )
            elif role == "worker":
                processed = int(
                    run_worker_once(
                        queue,
                        candidates,
                        worker_id=worker_id,
                        discovery=discovery,
                        lifecycle=lifecycle,
                    )
                    is not None
                )
            elif role == "browser-worker" and browser_executor is not None:
                processed = int(
                    run_browser_worker_once(
                        queue,
                        applications,
                        browser_executor,
                        worker_id=worker_id,
                        fixture_base_url=fixture_base_url,
                    )
                    is not None
                )
            elif role == "controlled-submission-worker" and controlled_executor is not None:
                for candidate in candidates.list_candidates():
                    applications.reconcile_stale_controlled_submissions(candidate.candidate_id)
                processed = int(
                    run_controlled_submission_worker_once(
                        queue,
                        applications,
                        controlled_executor,
                        worker_id=worker_id,
                    )
                    is not None
                )
            else:
                raise ValueError(f"unsupported runtime role: {role}")
            redis.set(
                channel,
                json.dumps(
                    {
                        "role": role,
                        "status": "ready",
                        "processed": processed,
                        "worker_id": worker_id,
                    }
                ),
                ex=90,
            )
            time.sleep(
                15 if role in {"worker", "browser-worker", "controlled-submission-worker"} else 30
            )
    finally:
        if fixture_server is not None:
            fixture_server.shutdown()
            fixture_server.server_close()
        if fixture_thread is not None:
            fixture_thread.join(timeout=5)
        if controlled_executor is not None:
            controlled_executor.abort()
