from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.applications import (
    ApplicationConflictError,
    ApplicationService,
    DryRunCommand,
    SyntheticSubmissionRequest,
)
from app.browser.fakes import DeterministicBrowserExecutor
from app.candidates.service import CandidateService
from app.db import build_session_factory
from app.discovery.verification import StoredFixtureJobSourceVerifier, VerificationEvidence
from app.domain.enums import ApplicationState
from app.domain.models import (
    Application,
    ApplicationEvent,
    Base,
    GlobalJob,
    SubmissionAuthorizationRecord,
)
from app.job_service import DiscoveryRequest, JobService
from app.tasks import TaskQueue


class CountingFixtureVerifier(StoredFixtureJobSourceVerifier):
    def __init__(self, status: Literal["open", "closed", "error"] = "open") -> None:
        super().__init__(status)
        self.calls = 0

    def verify(self, job: GlobalJob, *, checked_at: datetime | None = None) -> VerificationEvidence:
        self.calls += 1
        return super().verify(job, checked_at=checked_at)


class SequentialFixtureVerifier(StoredFixtureJobSourceVerifier):
    def __init__(self, statuses: tuple[Literal["open", "closed", "error"], ...]) -> None:
        super().__init__()
        self._statuses = list(statuses)
        self.calls = 0

    def verify(self, job: GlobalJob, *, checked_at: datetime | None = None) -> VerificationEvidence:
        self.calls += 1
        status = self._statuses.pop(0)
        return StoredFixtureJobSourceVerifier(status).verify(job, checked_at=checked_at)


def _services(
    candidates_root: Path,
    runtime_root: Path,
    verifier: StoredFixtureJobSourceVerifier | None = None,
) -> tuple[JobService, ApplicationService, sessionmaker[Session]]:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(candidates_root)
    source_verifier = verifier or StoredFixtureJobSourceVerifier()
    return (
        JobService(sessions, candidates, source_verifier),
        ApplicationService(
            sessions,
            candidates,
            runtime_root,
            source_verifier=source_verifier,
        ),
        sessions,
    )


def _lower_fixture_threshold(candidates_root: Path) -> None:
    path = candidates_root / "example_candidate" / "scoring_rules.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["application_threshold"] = 40
    data["human_review_threshold"] = 30
    path.write_text(json.dumps(data), encoding="utf-8")


def _execute_browser_dry_run(
    applications: ApplicationService,
    sessions: sessionmaker[Session],
    runtime_root: Path,
) -> None:
    queue = TaskQueue(sessions)
    task = queue.claim(worker_id="identity-browser-worker")
    assert task is not None and task.kind == "browser_dry_run"
    result = applications.execute_browser_task(
        queue,
        task,
        worker_id="identity-browser-worker",
        executor=DeterministicBrowserExecutor(runtime_root),
        fixture_base_url="http://127.0.0.1:8090/application",
    )
    assert result.status == "completed"


def _discover_greenhouse_job(
    jobs: JobService,
    *,
    external_id: int,
    requisition_id: str,
    title: str = "Machine Learning Engineer",
    source_host: str = "boards.greenhouse.io",
) -> UUID:
    result = jobs.discover(
        DiscoveryRequest(
            candidate_id="example_candidate",
            platform="greenhouse",
            company="Fictional Robotics Ltd",
            company_domain="fictional-robotics.invalid",
            payloads=(
                {
                    "id": external_id,
                    "internal_job_id": requisition_id,
                    "title": title,
                    "content": "Build truthful synthetic machine-learning services.",
                    "location": {"name": "Exampleton"},
                    "absolute_url": (f"https://{source_host}/fictional/jobs/{external_id}"),
                },
            ),
        ),
        f"discover-{external_id}",
    )
    job_id = result.job_ids[0]
    jobs.analyze("example_candidate", job_id, f"analyze-{external_id}")
    return job_id


def test_cross_source_same_requisition_blocks_second_material_generation(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _lower_fixture_threshold(copied_candidates_root)
    jobs, applications, sessions = _services(copied_candidates_root, tmp_path / "runtime")
    first_job_id = _discover_greenhouse_job(
        jobs,
        external_id=7101,
        requisition_id="REQ-IDENTITY-71",
        source_host="boards.greenhouse.io",
    )
    second_job_id = _discover_greenhouse_job(
        jobs,
        external_id=7102,
        requisition_id="req identity 71",
        source_host="job-boards.greenhouse.io",
    )

    assert jobs.get_job("example_candidate", second_job_id).possible_duplicate
    applications.generate_materials("example_candidate", first_job_id, "generate-7101")

    with pytest.raises(ApplicationConflictError, match="requisition or equivalent job"):
        applications.generate_materials("example_candidate", second_job_id, "generate-7102")

    with sessions() as session:
        assert session.scalar(select(func.count(Application.id))) == 1


def test_renamed_same_requisition_blocks_second_material_generation(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _lower_fixture_threshold(copied_candidates_root)
    jobs, applications, sessions = _services(copied_candidates_root, tmp_path / "runtime")
    first_job_id = _discover_greenhouse_job(
        jobs,
        external_id=7201,
        requisition_id="REQ-IDENTITY-72",
        title="Machine Learning Engineer",
    )
    renamed_job_id = _discover_greenhouse_job(
        jobs,
        external_id=7202,
        requisition_id="req identity 72",
        title="Senior Applied AI Engineer",
    )

    applications.generate_materials("example_candidate", first_job_id, "generate-7201")

    with pytest.raises(ApplicationConflictError, match="requisition or equivalent job"):
        applications.generate_materials("example_candidate", renamed_job_id, "generate-7202")

    with sessions() as session:
        assert session.scalar(select(func.count(Application.id))) == 1


def test_distinct_requisitions_allow_distinct_applications(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _lower_fixture_threshold(copied_candidates_root)
    jobs, applications, sessions = _services(copied_candidates_root, tmp_path / "runtime")
    first_job_id = _discover_greenhouse_job(
        jobs,
        external_id=7301,
        requisition_id="REQ-IDENTITY-73-A",
    )
    second_job_id = _discover_greenhouse_job(
        jobs,
        external_id=7302,
        requisition_id="REQ-IDENTITY-73-B",
    )

    first = applications.generate_materials("example_candidate", first_job_id, "generate-7301")
    second = applications.generate_materials("example_candidate", second_job_id, "generate-7302")

    assert first.application_id != second.application_id
    with sessions() as session:
        assert session.scalar(select(func.count(Application.id))) == 2


@pytest.mark.parametrize("status", ["closed", "error"])
def test_failed_source_revalidation_persists_evidence_without_creating_application(
    copied_candidates_root: Path,
    tmp_path: Path,
    status: Literal["closed", "error"],
) -> None:
    _lower_fixture_threshold(copied_candidates_root)
    verifier = CountingFixtureVerifier(status)
    jobs, applications, sessions = _services(
        copied_candidates_root,
        tmp_path / f"runtime-{status}",
        verifier,
    )
    job_id = _discover_greenhouse_job(
        jobs,
        external_id=7401,
        requisition_id=f"REQ-IDENTITY-74-{status}",
    )

    with pytest.raises(ApplicationConflictError, match="revalidated from its source"):
        applications.generate_materials("example_candidate", job_id, f"generate-7401-{status}")

    assert verifier.calls == 1
    with sessions() as session:
        job = session.get(GlobalJob, job_id)
        assert job is not None
        assert job.verification_status == status
        assert job.verification_checked_at is not None
        assert job.verification_evidence_sha256 is not None
        assert job.verification_evidence["reason"] == f"offline_fixture_{status}"
        assert session.scalar(select(func.count(Application.id))) == 0


def test_material_generation_replay_does_not_reverify_source(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _lower_fixture_threshold(copied_candidates_root)
    verifier = CountingFixtureVerifier()
    jobs, applications, _ = _services(
        copied_candidates_root,
        tmp_path / "runtime",
        verifier,
    )
    job_id = _discover_greenhouse_job(
        jobs,
        external_id=7501,
        requisition_id="REQ-IDENTITY-75",
    )

    first = applications.generate_materials("example_candidate", job_id, "generate-replay-7501")
    replay = applications.generate_materials("example_candidate", job_id, "generate-replay-7501")

    assert replay == first
    assert verifier.calls == 1


@pytest.mark.parametrize("final_status", ["closed", "error"])
def test_submission_revalidates_and_preserves_unconsumed_authorization_on_failure(
    copied_candidates_root: Path,
    tmp_path: Path,
    final_status: Literal["closed", "error"],
) -> None:
    _lower_fixture_threshold(copied_candidates_root)
    verifier = SequentialFixtureVerifier(("open", "open", final_status))
    runtime_root = tmp_path / f"runtime-submit-{final_status}"
    jobs, applications, sessions = _services(
        copied_candidates_root,
        runtime_root,
        verifier,
    )
    job_id = _discover_greenhouse_job(
        jobs,
        external_id=7601,
        requisition_id=f"REQ-IDENTITY-76-{final_status}",
    )
    generated = applications.generate_materials(
        "example_candidate", job_id, f"generate-7601-{final_status}"
    )
    applications.approve_materials(
        "example_candidate", generated.application_id, f"approve-7601-{final_status}"
    )
    applications.start("example_candidate", generated.application_id, f"start-7601-{final_status}")
    applications.dry_run(
        "example_candidate",
        generated.application_id,
        DryRunCommand(),
        f"dry-run-7601-{final_status}",
    )
    _execute_browser_dry_run(applications, sessions, runtime_root)
    authorization = applications.authorize(
        "example_candidate", generated.application_id, f"authorize-7601-{final_status}"
    )

    with pytest.raises(ApplicationConflictError, match="could not confirm the opening"):
        applications.submit_synthetic(
            "example_candidate",
            generated.application_id,
            SyntheticSubmissionRequest(
                authorization_id=authorization.authorization_id,
                synthetic_fixture_acknowledged=True,
            ),
            f"submit-7601-{final_status}",
        )

    assert verifier.calls == 3
    with sessions() as session:
        application = session.get(Application, generated.application_id)
        record = session.get(SubmissionAuthorizationRecord, authorization.authorization_id)
        job = session.get(GlobalJob, job_id)
        assert application is not None and application.state is ApplicationState.READY_TO_SUBMIT
        assert record is not None and record.consumed_at is None
        assert job is not None and job.verification_status == final_status
        terminal_events = session.scalars(
            select(ApplicationEvent.event_type).where(
                ApplicationEvent.application_id == generated.application_id,
                ApplicationEvent.event_type.in_(
                    ("SYNTHETIC_SUBMISSION_STARTED", "SYNTHETIC_APPLICATION_SUBMITTED")
                ),
            )
        ).all()
        assert terminal_events == []
