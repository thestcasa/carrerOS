from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from typing import Literal
from uuid import UUID

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.applications import (
    ApplicationConflictError,
    ApplicationService,
    DryRunCommand,
)
from app.browser import BrowserFailureCategory, BrowserWorkerFailure, PlaywrightDryRunRequest
from app.browser.contracts import BrowserExecutor, PlaywrightDryRunResult
from app.browser.fakes import DeterministicBrowserExecutor
from app.candidates.service import CandidateService
from app.db import build_session_factory
from app.discovery.verification import StoredFixtureJobSourceVerifier
from app.domain.enums import ApplicationState
from app.domain.models import (
    ApplicationArtifact,
    Base,
    BrowserSession,
    WorkflowTask,
)
from app.job_service import DiscoveryRequest, JobService
from app.tasks import TaskQueue, TaskView

_CANDIDATE_ID = "example_candidate"
_FIXTURE_URL = "http://127.0.0.1:8090/application"


def _services(
    candidates_root: Path, runtime_root: Path
) -> tuple[JobService, ApplicationService, TaskQueue, sessionmaker[Session]]:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(candidates_root)
    verifier = StoredFixtureJobSourceVerifier()
    return (
        JobService(sessions, candidates, verifier),
        ApplicationService(
            sessions,
            candidates,
            runtime_root,
            human_action_session_verifier=lambda *_args: True,
            source_verifier=verifier,
        ),
        TaskQueue(sessions),
        sessions,
    )


def _lower_fixture_threshold(candidates_root: Path) -> None:
    path = candidates_root / _CANDIDATE_ID / "scoring_rules.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["application_threshold"] = 40
    data["human_review_threshold"] = 30
    path.write_text(json.dumps(data), encoding="utf-8")


def _queue_browser_task(
    candidates_root: Path,
    runtime_root: Path,
    *,
    external_id: int,
    challenge: Literal["captcha", "otp"] | None = None,
) -> tuple[ApplicationService, TaskQueue, sessionmaker[Session], UUID, TaskView]:
    _lower_fixture_threshold(candidates_root)
    jobs, applications, queue, sessions = _services(candidates_root, runtime_root)
    discovered = jobs.discover(
        DiscoveryRequest(
            candidate_id=_CANDIDATE_ID,
            platform="greenhouse",
            company="Fictional Browser Tasks Ltd",
            company_domain="browser-tasks.invalid",
            payloads=(
                {
                    "id": external_id,
                    "title": "Synthetic Browser Test Engineer",
                    "content": "Test deterministic, truthful synthetic browser workflows.",
                    "location": {"name": "Exampleton"},
                    "absolute_url": (f"https://boards.greenhouse.io/fictional/jobs/{external_id}"),
                },
            ),
        )
    )
    job_id = discovered.job_ids[0]
    jobs.analyze(_CANDIDATE_ID, job_id, f"analyze-browser-{external_id}")
    generated = applications.generate_materials(
        _CANDIDATE_ID, job_id, f"generate-browser-{external_id}"
    )
    applications.approve_materials(
        _CANDIDATE_ID, generated.application_id, f"approve-browser-{external_id}"
    )
    applications.start(_CANDIDATE_ID, generated.application_id, f"start-browser-{external_id}")
    queued_detail = applications.dry_run(
        _CANDIDATE_ID,
        generated.application_id,
        DryRunCommand(challenge=challenge),
        f"dry-run-browser-{external_id}",
    )
    assert queued_detail.state is ApplicationState.FORM_FILLING
    assert queued_detail.next_action == "Waiting for isolated browser worker"
    with sessions() as session:
        task_record = session.scalar(
            select(WorkflowTask).where(
                WorkflowTask.candidate_id == _CANDIDATE_ID,
                WorkflowTask.kind == "browser_dry_run",
            )
        )
        assert task_record is not None
        task = queue.get(task_record.id)
    assert task is not None
    return applications, queue, sessions, generated.application_id, task


def _claim(queue: TaskQueue, worker_id: str, now: datetime) -> TaskView:
    claimed = queue.claim(
        worker_id=worker_id,
        now=now,
        allowed_kinds=frozenset({"browser_dry_run"}),
    )
    assert claimed is not None
    return claimed


class _FailOnceExecutor:
    def __init__(self, delegate: BrowserExecutor) -> None:
        self._delegate = delegate
        self.requests: list[PlaywrightDryRunRequest] = []

    def run(self, request: PlaywrightDryRunRequest) -> PlaywrightDryRunResult:
        self.requests.append(request)
        if len(self.requests) == 1:
            # Materialize the profile to prove the retry reuses the original session.
            self._delegate.run(request)
            raise BrowserWorkerFailure(
                BrowserFailureCategory.TRANSIENT_NETWORK,
                retryable=True,
                safe_details="Synthetic network interruption.",
            )
        return self._delegate.run(request)


class _AlwaysFailExecutor:
    def __init__(self, *, retryable: bool) -> None:
        self.retryable = retryable

    def run(self, request: PlaywrightDryRunRequest) -> PlaywrightDryRunResult:
        del request
        raise BrowserWorkerFailure(
            BrowserFailureCategory.SELECTOR_FAILURE,
            retryable=self.retryable,
            safe_details="Synthetic form mapping needs review.",
        )


def test_dry_run_enqueues_without_executing_browser(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    applications, _queue, sessions, application_id, task = _queue_browser_task(
        copied_candidates_root, tmp_path / "runtime", external_id=6101
    )

    assert task.status == "pending"
    assert task.attempts == 0
    assert UUID(str(task.payload["application_id"])) == application_id
    assert applications.get_application(_CANDIDATE_ID, application_id).state is (
        ApplicationState.FORM_FILLING
    )
    with sessions() as session:
        assert (
            session.scalars(
                select(ApplicationArtifact).where(
                    ApplicationArtifact.application_id == application_id,
                    ApplicationArtifact.kind.like("browser_%"),
                )
            ).all()
            == []
        )


def test_success_publishes_immutable_browser_evidence_and_advances_state(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    runtime_root = tmp_path / "runtime"
    applications, queue, _sessions, application_id, _task = _queue_browser_task(
        copied_candidates_root, runtime_root, external_id=6102
    )
    now = datetime(2026, 8, 6, 9, tzinfo=UTC)
    claimed = _claim(queue, "browser-worker-success", now)

    completed = applications.execute_browser_task(
        queue,
        claimed,
        worker_id="browser-worker-success",
        executor=DeterministicBrowserExecutor(runtime_root),
        fixture_base_url=_FIXTURE_URL,
    )

    assert completed.status == "completed", completed.model_dump()
    assert applications.get_application(_CANDIDATE_ID, application_id).state is (
        ApplicationState.READY_TO_SUBMIT
    )
    artifacts = {
        item.kind: item
        for item in applications.list_artifacts(_CANDIDATE_ID, application_id)
        if item.kind.startswith("browser_")
    }
    assert set(artifacts) == {
        "browser_pre_submit_screenshot",
        "browser_final_page_snapshot",
        "browser_attempt_manifest",
    }
    assert all(item.immutable and item.version == 1 for item in artifacts.values())
    screenshot = applications.artifact_path(
        _CANDIDATE_ID,
        application_id,
        artifacts["browser_pre_submit_screenshot"].artifact_id,
    ).read_bytes()
    final_page = applications.artifact_path(
        _CANDIDATE_ID,
        application_id,
        artifacts["browser_final_page_snapshot"].artifact_id,
    ).read_bytes()
    assert screenshot.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"Fictional pre-submit page" in final_page
    assert (
        artifacts["browser_pre_submit_screenshot"].sha256 == hashlib.sha256(screenshot).hexdigest()
    )
    assert artifacts["browser_final_page_snapshot"].sha256 == hashlib.sha256(final_page).hexdigest()


def test_browser_execution_holds_candidate_lifecycle_fence(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    runtime_root = tmp_path / "runtime"
    applications, queue, _sessions, _application_id, _task = _queue_browser_task(
        copied_candidates_root, runtime_root, external_id=6110
    )
    claimed = _claim(queue, "browser-worker-fenced", datetime.now(UTC))
    started = Event()
    acquired = Event()
    contender = CandidateService(copied_candidates_root)
    delegate = DeterministicBrowserExecutor(runtime_root)
    worker: Thread | None = None

    class LifecycleProbeExecutor:
        def run(self, request: PlaywrightDryRunRequest) -> PlaywrightDryRunResult:
            nonlocal worker

            def contend() -> None:
                started.set()
                with contender.lifecycle_fence(request.candidate_id):
                    acquired.set()

            worker = Thread(target=contend)
            worker.start()
            assert started.wait(timeout=5)
            assert not acquired.wait(timeout=0.1)
            return delegate.run(request)

    completed = applications.execute_browser_task(
        queue,
        claimed,
        worker_id="browser-worker-fenced",
        executor=LifecycleProbeExecutor(),
        fixture_base_url=_FIXTURE_URL,
    )

    assert completed.status == "completed"
    assert acquired.wait(timeout=5)
    assert worker is not None
    worker.join(timeout=5)
    assert not worker.is_alive()


def test_executor_cannot_import_evidence_from_outside_candidate_session(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    runtime_root = tmp_path / "runtime"
    applications, queue, _sessions, application_id, task = _queue_browser_task(
        copied_candidates_root, runtime_root, external_id=6111
    )
    outside_png = tmp_path / "outside.png"
    outside_png.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c63606060f80f0001040100c89f17d90000000049454e44ae426082"
        )
    )
    delegate = DeterministicBrowserExecutor(runtime_root)

    class OutsideEvidenceExecutor:
        def run(self, request: PlaywrightDryRunRequest) -> PlaywrightDryRunResult:
            return delegate.run(request).model_copy(update={"screenshot_path": outside_png})

    claimed = _claim(queue, "browser-worker-outside", datetime.now(UTC))
    failed = applications.execute_browser_task(
        queue,
        claimed,
        worker_id="browser-worker-outside",
        executor=OutsideEvidenceExecutor(),
        fixture_base_url=_FIXTURE_URL,
    )

    assert failed.status == "failed"
    assert failed.last_error_category == BrowserFailureCategory.VALIDATION_FAILURE.value
    assert applications.get_application(_CANDIDATE_ID, application_id).state is (
        ApplicationState.HUMAN_ACTION_REQUIRED
    )
    evidence_root = runtime_root / "candidates" / _CANDIDATE_ID / "browser_evidence"
    assert not evidence_root.exists()
    assert task.attempts == 0


def test_transient_failure_retries_in_the_same_browser_session(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    runtime_root = tmp_path / "runtime"
    applications, queue, _sessions, application_id, task = _queue_browser_task(
        copied_candidates_root, runtime_root, external_id=6103
    )
    executor = _FailOnceExecutor(DeterministicBrowserExecutor(runtime_root))
    now = datetime.now(UTC)
    first = _claim(queue, "browser-worker-retry", now)

    pending = applications.execute_browser_task(
        queue,
        first,
        worker_id="browser-worker-retry",
        executor=executor,
        fixture_base_url=_FIXTURE_URL,
        now=now,
    )
    assert pending.status == "pending"
    assert pending.last_error_category == BrowserFailureCategory.TRANSIENT_NETWORK.value
    assert applications.get_application(_CANDIDATE_ID, application_id).state is (
        ApplicationState.FORM_FILLING
    )

    second = _claim(queue, "browser-worker-retry", pending.scheduled_for + timedelta(seconds=1))
    completed = applications.execute_browser_task(
        queue,
        second,
        worker_id="browser-worker-retry",
        executor=executor,
        fixture_base_url=_FIXTURE_URL,
    )

    assert completed.status == "completed"
    assert second.attempts == 2
    assert [request.session_id for request in executor.requests] == [
        UUID(str(task.payload["session_id"])),
        UUID(str(task.payload["session_id"])),
    ]
    manifest = next(
        item
        for item in applications.list_artifacts(_CANDIDATE_ID, application_id)
        if item.kind == "browser_attempt_manifest"
    )
    payload = json.loads(
        applications.artifact_path(_CANDIDATE_ID, application_id, manifest.artifact_id).read_text(
            encoding="utf-8"
        )
    )
    assert manifest.version == 1
    assert manifest.metadata["attempt"] == 2
    assert payload["recovered_profile"] is True


def test_stale_lease_result_is_discarded_before_application_mutation(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    runtime_root = tmp_path / "runtime"
    applications, queue, sessions, application_id, task = _queue_browser_task(
        copied_candidates_root, runtime_root, external_id=6104
    )
    now = datetime.now(UTC)
    stale = _claim(queue, "browser-worker-stale", now)
    delegate = DeterministicBrowserExecutor(runtime_root)

    class ReclaimingExecutor:
        def run(self, request: PlaywrightDryRunRequest) -> PlaywrightDryRunResult:
            result = delegate.run(request)
            reclaimed = queue.claim(
                worker_id="browser-worker-new",
                now=now + timedelta(minutes=6),
                allowed_kinds=frozenset({"browser_dry_run"}),
            )
            assert reclaimed is not None and reclaimed.task_id == task.task_id
            return result

    current = applications.execute_browser_task(
        queue,
        stale,
        worker_id="browser-worker-stale",
        executor=ReclaimingExecutor(),
        fixture_base_url=_FIXTURE_URL,
    )

    assert current.status == "running"
    assert current.locked_by == "browser-worker-new"
    assert current.attempts == 2
    assert applications.get_application(_CANDIDATE_ID, application_id).state is (
        ApplicationState.FORM_FILLING
    )
    with sessions() as session:
        assert (
            session.scalars(
                select(ApplicationArtifact).where(
                    ApplicationArtifact.application_id == application_id,
                    ApplicationArtifact.kind.like("browser_%"),
                )
            ).all()
            == []
        )
    stale_evidence = (
        runtime_root
        / "candidates"
        / _CANDIDATE_ID
        / "browser_evidence"
        / str(task.task_id)
        / "attempt-1"
    )
    assert not stale_evidence.exists()

    completed = applications.execute_browser_task(
        queue,
        current,
        worker_id="browser-worker-new",
        executor=delegate,
        fixture_base_url=_FIXTURE_URL,
    )
    assert completed.status == "completed"
    assert applications.get_application(_CANDIDATE_ID, application_id).state is (
        ApplicationState.READY_TO_SUBMIT
    )


@pytest.mark.parametrize("retryable", [False, True])
def test_terminal_browser_failure_escalates_with_action_and_notification(
    copied_candidates_root: Path,
    tmp_path: Path,
    retryable: bool,
) -> None:
    runtime_root = tmp_path / "runtime"
    applications, queue, _sessions, application_id, _task = _queue_browser_task(
        copied_candidates_root,
        runtime_root,
        external_id=6105 if retryable else 6106,
    )
    now = datetime(2026, 8, 6, 12, tzinfo=UTC)
    failed: TaskView | None = None
    attempts = 3 if retryable else 1
    for attempt in range(attempts):
        claimed = _claim(queue, f"browser-worker-failure-{attempt}", now)
        failed = applications.execute_browser_task(
            queue,
            claimed,
            worker_id=f"browser-worker-failure-{attempt}",
            executor=_AlwaysFailExecutor(retryable=retryable),
            fixture_base_url=_FIXTURE_URL,
            now=now,
        )
        now += timedelta(seconds=31)

    assert failed is not None and failed.status == "failed"
    assert failed.attempts == attempts
    assert failed.last_error_category == BrowserFailureCategory.SELECTOR_FAILURE.value
    assert applications.get_application(_CANDIDATE_ID, application_id).state is (
        ApplicationState.HUMAN_ACTION_REQUIRED
    )
    actions = applications.list_human_actions(_CANDIDATE_ID)
    assert len(actions) == 1
    assert actions[0].application_id == application_id
    assert actions[0].kind == "browser_failure"
    assert actions[0].status == "pending"
    notifications = applications.list_notifications(_CANDIDATE_ID)
    assert len(notifications) == 1
    assert notifications[0].application_id == application_id
    assert notifications[0].event_type == "browser_dry_run_failed"
    assert notifications[0].immediate


def test_challenge_creates_visible_action_for_the_exact_browser_session(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    runtime_root = tmp_path / "runtime"
    applications, queue, sessions, application_id, task = _queue_browser_task(
        copied_candidates_root,
        runtime_root,
        external_id=6107,
        challenge="captcha",
    )
    now = datetime(2026, 8, 6, 13, tzinfo=UTC)
    claimed = _claim(queue, "browser-worker-challenge", now)
    completed = applications.execute_browser_task(
        queue,
        claimed,
        worker_id="browser-worker-challenge",
        executor=DeterministicBrowserExecutor(runtime_root),
        fixture_base_url=_FIXTURE_URL,
    )

    assert completed.status == "completed"
    assert applications.get_application(_CANDIDATE_ID, application_id).state is (
        ApplicationState.HUMAN_ACTION_REQUIRED
    )
    actions = applications.list_human_actions(_CANDIDATE_ID)
    assert len(actions) == 1
    assert actions[0].kind == "captcha"
    assert actions[0].screenshot_available
    assert actions[0].browser_session_id == UUID(str(task.payload["session_id"]))
    with sessions() as session:
        browser_session = session.get(BrowserSession, actions[0].browser_session_id)
        assert browser_session is not None
        assert browser_session.application_id == application_id
        assert browser_session.status == "human_action_required"


def test_tampered_browser_evidence_denies_authorization_and_archive(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    runtime_root = tmp_path / "runtime"
    applications, queue, _sessions, application_id, _task = _queue_browser_task(
        copied_candidates_root, runtime_root, external_id=6108
    )
    now = datetime(2026, 8, 6, 14, tzinfo=UTC)
    claimed = _claim(queue, "browser-worker-tamper", now)
    applications.execute_browser_task(
        queue,
        claimed,
        worker_id="browser-worker-tamper",
        executor=DeterministicBrowserExecutor(runtime_root),
        fixture_base_url=_FIXTURE_URL,
    )
    final_page = next(
        item
        for item in applications.list_artifacts(_CANDIDATE_ID, application_id)
        if item.kind == "browser_final_page_snapshot"
    )
    # The public view intentionally hides storage paths; resolve it through the verified accessor.
    path = applications.artifact_path(_CANDIDATE_ID, application_id, final_page.artifact_id)
    path.write_bytes(path.read_bytes() + b"<!-- tampered -->")

    with pytest.raises(ApplicationConflictError, match="submission gate denied"):
        applications.authorize(_CANDIDATE_ID, application_id, "authorize-tampered-browser")

    detail = applications.get_application(_CANDIDATE_ID, application_id)
    assert not detail.archive_available
    assert "archive_manifest" not in {
        item.kind for item in applications.list_artifacts(_CANDIDATE_ID, application_id)
    }
