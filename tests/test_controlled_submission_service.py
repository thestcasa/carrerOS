from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.applications import (
    ApplicationConflictError,
    ApplicationService,
    DryRunCommand,
    SettingsUpdate,
)
from app.browser.fakes import DeterministicBrowserExecutor
from app.candidates.service import CandidateService
from app.db import build_session_factory
from app.discovery.verification import StoredFixtureJobSourceVerifier
from app.domain.enums import ApplicationState
from app.domain.models import (
    ApplicationArtifact,
    Base,
    CandidateSettingsRecord,
    ControlledSubmissionAttempt,
    HumanAction,
    NotificationRecord,
    SubmissionAuthorizationRecord,
)
from app.job_service import DiscoveryRequest, JobService
from app.submission import (
    ControlledAuthorizationRequest,
    ControlledGreenhouseFormPayload,
    ControlledSubmissionCommand,
    ControlledSubmissionError,
    ControlledSubmissionPreparationRequest,
    ControlledSubmissionRequest,
    ControlledSubmissionResult,
    ControlledSubmissionUncertainError,
    GreenhouseFormInspection,
    PreparedControlledSubmission,
)
from app.submission_gate import FinalClickPermit
from app.tasks import TaskQueue, TaskView

_CANDIDATE_ID = "example_candidate"
_PNG = b"\x89PNG\r\n\x1a\nfictional-controlled-evidence"


class _ControlledExecutor:
    def __init__(
        self,
        *,
        outcome: Literal["confirmed", "uncertain", "crash"] = "confirmed",
        after_prepare: Callable[[], None] | None = None,
        prepare_error: ControlledSubmissionError | None = None,
    ) -> None:
        self.outcome = outcome
        self.after_prepare = after_prepare
        self.prepare_error = prepare_error
        self.clicks = 0
        self.aborted = False
        self._target_url: str | None = None
        self.prepared_form: ControlledGreenhouseFormPayload | None = None

    def prepare(
        self, request: ControlledSubmissionPreparationRequest
    ) -> PreparedControlledSubmission:
        self._target_url = request.target_url
        self.prepared_form = request.form
        if self.after_prepare is not None:
            self.after_prepare()
        if self.prepare_error is not None:
            raise self.prepare_error
        return PreparedControlledSubmission(
            attempt_id=request.attempt_id,
            inspection=GreenhouseFormInspection(
                target_url=request.target_url,
                form_action=f"{request.target_url}/applications",
                form_fingerprint="b" * 64,
                required_selectors=("form#application_form #first_name",),
                submit_selector="form#application_form #submit_app",
                submit_control_count=1,
                human_verification_present=False,
            ),
            form_payload_sha256=request.form.sha256(),
            pre_click_screenshot_png=_PNG,
            pre_click_page_html=b"<!doctype html><p>Fictional pre-click page</p>",
        )

    def execute(
        self,
        request: ControlledSubmissionRequest,
        permit: FinalClickPermit,
    ) -> ControlledSubmissionResult:
        if self.outcome == "crash":
            raise SystemExit("fictional worker crash after arming")
        permit.consume(
            candidate_id=request.candidate_id,
            application_id=request.application_id,
            authorization_id=request.authorization_id,
            attempt_id=request.attempt_id,
        )
        self.clicks += 1
        if self.outcome == "uncertain":
            raise ControlledSubmissionUncertainError("fictional timeout after one click")
        assert self._target_url is not None
        return ControlledSubmissionResult(
            attempt_id=request.attempt_id,
            click_invoked=True,
            confirmation_detected=True,
            confirmation_reference="fictional-greenhouse-confirmation",
            final_url=f"{self._target_url}/confirmation",
            screenshot_png=_PNG,
            final_page_html=b"<!doctype html><p>Fictional confirmation</p>",
        )

    def abort(self) -> None:
        self.aborted = True


def _enable_candidate_submission(candidates_root: Path) -> None:
    scoring_path = candidates_root / _CANDIDATE_ID / "scoring_rules.json"
    scoring = json.loads(scoring_path.read_text(encoding="utf-8"))
    scoring["application_threshold"] = 40
    scoring["human_review_threshold"] = 30
    scoring_path.write_text(json.dumps(scoring), encoding="utf-8")
    profile_path = candidates_root / _CANDIDATE_ID / "profile.yaml"
    profile_path.write_text(
        profile_path.read_text(encoding="utf-8").replace(
            "automatic_submission_enabled: false",
            "automatic_submission_enabled: true",
        ),
        encoding="utf-8",
    )


def _services(
    candidates_root: Path,
    runtime_root: Path,
    *,
    controlled_enabled: bool,
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
            source_verifier=verifier,
            controlled_submission_enabled=controlled_enabled,
        ),
        TaskQueue(sessions),
        sessions,
    )


def _ready_application(
    jobs: JobService,
    applications: ApplicationService,
    queue: TaskQueue,
    runtime_root: Path,
    *,
    external_id: int,
) -> UUID:
    discovered = jobs.discover(
        DiscoveryRequest(
            candidate_id=_CANDIDATE_ID,
            platform="greenhouse",
            company="Fictional Controlled Robotics Ltd",
            company_domain="controlled-robotics.invalid",
            payloads=(
                {
                    "id": external_id,
                    "title": "Machine Learning Engineer",
                    "content": "Build truthful synthetic machine-learning services.",
                    "location": {"name": "Exampleton"},
                    "absolute_url": (f"https://boards.greenhouse.io/fictional/jobs/{external_id}"),
                },
            ),
        )
    )
    job_id = discovered.job_ids[0]
    jobs.analyze(_CANDIDATE_ID, job_id, f"analyze-controlled-{external_id}")
    generated = applications.generate_materials(
        _CANDIDATE_ID, job_id, f"generate-controlled-{external_id}"
    )
    applications.approve_materials(
        _CANDIDATE_ID,
        generated.application_id,
        f"approve-controlled-{external_id}",
    )
    applications.start(
        _CANDIDATE_ID,
        generated.application_id,
        f"start-controlled-{external_id}",
    )
    applications.dry_run(
        _CANDIDATE_ID,
        generated.application_id,
        DryRunCommand(),
        f"dry-run-controlled-{external_id}",
    )
    browser_task = queue.claim(
        worker_id="controlled-test-dry-run",
        allowed_kinds=frozenset({"browser_dry_run"}),
    )
    assert browser_task is not None
    result = applications.execute_browser_task(
        queue,
        browser_task,
        worker_id="controlled-test-dry-run",
        executor=DeterministicBrowserExecutor(runtime_root),
        fixture_base_url="http://127.0.0.1:8090/application",
    )
    assert result.status == "completed"
    applications.update_settings(
        SettingsUpdate(
            candidate_id=_CANDIDATE_ID,
            automation_mode="approval_required",
            allowed_ats_adapters=("greenhouse",),
            tested_ats_adapters=("greenhouse",),
            dry_run_acceptance_passed=True,
        ),
        f"controlled-settings-{external_id}",
    )
    assert (
        applications.get_application(_CANDIDATE_ID, generated.application_id).state
        is ApplicationState.READY_TO_SUBMIT
    )
    return generated.application_id


def _authorize_and_queue(
    applications: ApplicationService,
    queue: TaskQueue,
    application_id: UUID,
    *,
    suffix: str,
) -> tuple[UUID, TaskView]:
    authorization = applications.authorize_controlled(
        _CANDIDATE_ID,
        application_id,
        ControlledAuthorizationRequest(approval_acknowledged=True),
        f"controlled-authorize-{suffix}",
    )
    execution = applications.queue_controlled_submission(
        _CANDIDATE_ID,
        application_id,
        ControlledSubmissionCommand(authorization_id=authorization.authorization_id),
        f"controlled-queue-{suffix}",
    )
    task = queue.claim(
        worker_id=f"controlled-worker-{suffix}",
        allowed_kinds=frozenset({"controlled_submission"}),
    )
    assert task is not None and task.task_id == execution.task_id
    return authorization.authorization_id, task


def test_controlled_submission_is_disabled_before_authorization(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _jobs, applications, _queue, sessions = _services(
        copied_candidates_root, tmp_path / "runtime", controlled_enabled=False
    )
    application_id = UUID("00000000-0000-0000-0000-000000000801")

    with pytest.raises(ApplicationConflictError, match="disabled"):
        applications.authorize_controlled(
            _CANDIDATE_ID,
            application_id,
            ControlledAuthorizationRequest(approval_acknowledged=True),
            "disabled-controlled-authorization",
        )

    with sessions() as session:
        assert session.scalar(select(SubmissionAuthorizationRecord)) is None
        assert session.scalar(select(ControlledSubmissionAttempt)) is None


def test_autonomous_controlled_confirmation_queues_once_clicks_once_and_archives_evidence(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _enable_candidate_submission(copied_candidates_root)
    jobs, applications, queue, sessions = _services(
        copied_candidates_root, tmp_path / "runtime", controlled_enabled=True
    )
    application_id = _ready_application(
        jobs, applications, queue, tmp_path / "runtime", external_id=802
    )
    applications.update_settings(
        SettingsUpdate(
            candidate_id=_CANDIDATE_ID,
            automation_mode="autonomous",
            explicit_autonomy_confirmation=True,
        ),
        "enable-controlled-autonomy-802",
    )
    queued = applications.enqueue_autonomous_controlled_submissions(_CANDIDATE_ID)
    assert len(queued) == 1
    assert applications.enqueue_autonomous_controlled_submissions(_CANDIDATE_ID) == ()
    task = queue.claim(
        worker_id="controlled-worker-success",
        allowed_kinds=frozenset({"controlled_submission"}),
    )
    assert task is not None and task.task_id == queued[0].task_id
    authorization_id = queued[0].authorization_id
    executor = _ControlledExecutor()

    completed = applications.execute_controlled_submission_task(
        queue,
        task,
        worker_id="controlled-worker-success",
        executor=executor,
    )

    assert completed.status == "completed"
    assert executor.clicks == 1
    assert executor.prepared_form is not None
    assert executor.prepared_form.first_name == "Morgan"
    assert executor.prepared_form.last_name == "Example"
    execution = applications.get_controlled_submission(_CANDIDATE_ID, application_id)
    assert execution.status == "confirmed"
    assert execution.successful
    assert execution.application_state is ApplicationState.CONFIRMED
    artifacts = applications.list_artifacts(_CANDIDATE_ID, application_id)
    kinds = {artifact.kind for artifact in artifacts}
    assert "submission_confirmation_screenshot" in kinds
    assert "submission_receipt" in kinds
    with sessions() as session:
        authorization = session.get(SubmissionAuthorizationRecord, authorization_id)
        assert authorization is not None and authorization.consumed_at is not None


def test_timeout_after_click_is_unknown_terminal_and_never_requeued(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _enable_candidate_submission(copied_candidates_root)
    jobs, applications, queue, sessions = _services(
        copied_candidates_root, tmp_path / "runtime", controlled_enabled=True
    )
    application_id = _ready_application(
        jobs, applications, queue, tmp_path / "runtime", external_id=803
    )
    _authorization_id, task = _authorize_and_queue(
        applications, queue, application_id, suffix="uncertain"
    )
    executor = _ControlledExecutor(outcome="uncertain")

    failed = applications.execute_controlled_submission_task(
        queue,
        task,
        worker_id="controlled-worker-uncertain",
        executor=executor,
    )

    assert failed.status == "failed"
    assert failed.last_error_retryable is False
    assert executor.clicks == 1
    assert (
        queue.claim(
            worker_id="forbidden-retry",
            allowed_kinds=frozenset({"controlled_submission"}),
        )
        is None
    )
    execution = applications.get_controlled_submission(_CANDIDATE_ID, application_id)
    assert execution.status == "unknown_after_click"
    assert execution.application_state is ApplicationState.UNKNOWN_AFTER_CLICK
    assert not execution.successful and not execution.retryable
    with sessions() as session:
        assert session.scalar(select(HumanAction)) is not None
        assert session.scalar(select(NotificationRecord)) is not None
        receipt = session.scalar(
            select(ApplicationArtifact).where(
                ApplicationArtifact.kind == "controlled_submission_unknown_receipt"
            )
        )
        assert receipt is not None and receipt.immutable


def test_policy_change_after_prepare_denies_before_click_without_consuming_authorization(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _enable_candidate_submission(copied_candidates_root)
    jobs, applications, queue, sessions = _services(
        copied_candidates_root, tmp_path / "runtime", controlled_enabled=True
    )
    application_id = _ready_application(
        jobs, applications, queue, tmp_path / "runtime", external_id=804
    )
    authorization_id, task = _authorize_and_queue(
        applications, queue, application_id, suffix="policy-drift"
    )

    def stop_after_prepare() -> None:
        with sessions.begin() as session:
            settings = session.scalar(select(CandidateSettingsRecord))
            assert settings is not None
            settings.tested_ats_adapters = []

    executor = _ControlledExecutor(after_prepare=stop_after_prepare)
    failed = applications.execute_controlled_submission_task(
        queue,
        task,
        worker_id="controlled-worker-policy-drift",
        executor=executor,
    )

    assert failed.status == "failed"
    assert executor.clicks == 0
    assert (
        applications.get_application(_CANDIDATE_ID, application_id).state
        is ApplicationState.READY_TO_SUBMIT
    )
    with sessions() as session:
        authorization = session.get(SubmissionAuthorizationRecord, authorization_id)
        attempt = session.scalar(select(ControlledSubmissionAttempt))
        assert authorization is not None and authorization.consumed_at is None
        assert attempt is not None and attempt.status == "denied"

    applications.update_settings(
        SettingsUpdate(candidate_id=_CANDIDATE_ID, tested_ats_adapters=("greenhouse",)),
        "resume-controlled-after-policy-drift",
    )
    _retry_authorization, retry_task = _authorize_and_queue(
        applications, queue, application_id, suffix="policy-drift-retry"
    )
    retry_executor = _ControlledExecutor()
    completed = applications.execute_controlled_submission_task(
        queue,
        retry_task,
        worker_id="controlled-worker-policy-drift-retry",
        executor=retry_executor,
    )
    assert completed.status == "completed"
    assert retry_executor.clicks == 1
    with sessions() as session:
        attempts = tuple(session.scalars(select(ControlledSubmissionAttempt)).all())
        assert len(attempts) == 2
        assert {attempt.status for attempt in attempts} == {"denied", "confirmed"}


def test_human_verification_pauses_before_click_and_creates_a_human_action(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _enable_candidate_submission(copied_candidates_root)
    jobs, applications, queue, sessions = _services(
        copied_candidates_root, tmp_path / "runtime", controlled_enabled=True
    )
    application_id = _ready_application(
        jobs, applications, queue, tmp_path / "runtime", external_id=806
    )
    authorization_id, task = _authorize_and_queue(
        applications, queue, application_id, suffix="captcha"
    )
    executor = _ControlledExecutor(
        prepare_error=ControlledSubmissionError(
            "fictional CAPTCHA",
            category="human_verification",
            human_action_kind="captcha",
        )
    )

    failed = applications.execute_controlled_submission_task(
        queue,
        task,
        worker_id="controlled-worker-captcha",
        executor=executor,
    )

    assert failed.status == "failed"
    assert executor.clicks == 0
    assert (
        applications.get_application(_CANDIDATE_ID, application_id).state
        is ApplicationState.HUMAN_ACTION_REQUIRED
    )
    with sessions() as session:
        authorization = session.get(SubmissionAuthorizationRecord, authorization_id)
        action = session.scalar(select(HumanAction))
        attempt = session.scalar(select(ControlledSubmissionAttempt))
        assert authorization is not None and authorization.consumed_at is None
        assert action is not None and action.kind == "controlled_captcha"
        assert attempt is not None and attempt.status == "denied"


def test_crash_after_arming_reconciles_unknown_without_a_second_click(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _enable_candidate_submission(copied_candidates_root)
    jobs, applications, queue, sessions = _services(
        copied_candidates_root, tmp_path / "runtime", controlled_enabled=True
    )
    application_id = _ready_application(
        jobs, applications, queue, tmp_path / "runtime", external_id=805
    )
    _authorization_id, task = _authorize_and_queue(
        applications, queue, application_id, suffix="crash"
    )
    executor = _ControlledExecutor(outcome="crash")

    with pytest.raises(SystemExit, match="fictional worker crash"):
        applications.execute_controlled_submission_task(
            queue,
            task,
            worker_id="controlled-worker-crash",
            executor=executor,
        )

    assert executor.clicks == 0
    with sessions() as session:
        attempt = session.scalar(select(ControlledSubmissionAttempt))
        assert attempt is not None
        assert attempt.status == "click_authorized"
        assert attempt.click_boundary_entered_at is not None
        reconcile_at = _utc(attempt.click_boundary_entered_at) + timedelta(minutes=3)

    assert applications.reconcile_stale_controlled_submissions(_CANDIDATE_ID, now=reconcile_at) == 1
    execution = applications.get_controlled_submission(_CANDIDATE_ID, application_id)
    assert execution.status == "unknown_after_click"
    assert execution.application_state is ApplicationState.UNKNOWN_AFTER_CLICK
    assert (
        queue.claim(
            worker_id="forbidden-crash-retry",
            allowed_kinds=frozenset({"controlled_submission"}),
        )
        is None
    )


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
