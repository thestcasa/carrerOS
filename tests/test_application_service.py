from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.applications import (
    ApplicationConflictError,
    ApplicationService,
    CorrespondenceIngestRequest,
    DryRunCommand,
    SettingsUpdate,
    SyntheticSubmissionRequest,
)
from app.candidates.service import CandidateCreateRequest, CandidateService
from app.db import build_session_factory
from app.domain.enums import ApplicationState
from app.domain.models import AdministrativeAuditRecord, Base
from app.job_service import DiscoveryRequest, JobService


def _services(
    candidates_root: Path, runtime_root: Path
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
    return (
        JobService(sessions, candidates),
        ApplicationService(sessions, candidates, runtime_root),
        sessions,
    )


def _job(job_service: JobService, external_id: int = 501) -> UUID:
    discovered = job_service.discover(
        DiscoveryRequest(
            candidate_id="example_candidate",
            platform="greenhouse",
            company="Fictional Robotics Ltd",
            company_domain="fictional-robotics.invalid",
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
    job_service.analyze("example_candidate", job_id, f"analyze-{external_id}")
    return job_id


def _lower_fixture_threshold(candidates_root: Path) -> None:
    path = candidates_root / "example_candidate" / "scoring_rules.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["application_threshold"] = 40
    data["human_review_threshold"] = 30
    path.write_text(json.dumps(data), encoding="utf-8")


def test_materials_dry_run_archive_and_confirmed_synthetic_submission_are_integrated(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _lower_fixture_threshold(copied_candidates_root)
    jobs, applications, _sessions = _services(copied_candidates_root, tmp_path / "runtime")
    job_id = _job(jobs)

    generated = applications.generate_materials(
        "example_candidate", job_id, "generate-materials-501"
    )
    assert generated.state is ApplicationState.REVIEW_PENDING
    assert {document.kind for document in generated.documents} == {"cv", "cover_letter"}
    assert all(document.evidence_ids for document in generated.documents)
    assert generated.review is not None and generated.review.semantic_passed

    applications.approve_materials(
        "example_candidate", generated.application_id, "approve-materials-501"
    )
    applications.start("example_candidate", generated.application_id, "start-application-501")
    ready = applications.dry_run(
        "example_candidate",
        generated.application_id,
        DryRunCommand(),
        "dry-run-501",
    )
    assert ready.state is ApplicationState.READY_TO_SUBMIT

    authorization = applications.authorize(
        "example_candidate", generated.application_id, "authorize-application-501"
    )
    artifacts = applications.list_artifacts("example_candidate", generated.application_id)
    artifact_kinds = {artifact.kind for artifact in artifacts}
    assert {
        "archive_manifest",
        "candidate_snapshot",
        "submitted_cv",
        "submitted_cover_letter",
        "submitted_answers",
        "pre_submit_screenshot",
        "final_page_snapshot",
        "submission_receipt",
        "application_audit",
    }.issubset(artifact_kinds)
    submitted_cv = next(artifact for artifact in artifacts if artifact.kind == "submitted_cv")
    assert (
        applications.artifact_path(
            "example_candidate", generated.application_id, submitted_cv.artifact_id
        )
        .read_bytes()
        .startswith(b"%PDF-1.4")
    )
    result = applications.submit_synthetic(
        "example_candidate",
        generated.application_id,
        SyntheticSubmissionRequest(
            authorization_id=authorization.authorization_id,
            synthetic_fixture_acknowledged=True,
            backend_confirmation_detected=True,
            confirmation_reference="synthetic-confirmation-501",
        ),
        "submit-synthetic-501",
    )

    assert result.successful
    assert result.state is ApplicationState.CONFIRMED
    detail = applications.get_application("example_candidate", generated.application_id)
    assert detail.confirmation_reference == "synthetic-confirmation-501"
    assert detail.archive_available
    artifacts = applications.list_artifacts("example_candidate", generated.application_id)
    assert {
        "archive_manifest",
        "cv",
        "cover_letter",
        "submitted_cv",
        "submitted_cover_letter",
        "submitted_answers",
        "submission_receipt",
    }.issubset({artifact.kind for artifact in artifacts})
    assert all(artifact.immutable for artifact in artifacts)

    correspondence = applications.ingest_correspondence(
        CorrespondenceIngestRequest(
            candidate_id="example_candidate",
            provider_message_id="fictional-interview-501",
            sender="recruiting@fictional-robotics.invalid",
            recipients=("morgan@example.invalid",),
            subject="Interview invitation for application 501",
            body_text="Please schedule an interview for the Machine Learning Engineer role.",
            received_at=datetime(2026, 8, 5, 14, tzinfo=UTC),
        ),
        "correspondence-interview-501",
    )
    assert correspondence.application_id == generated.application_id
    assert correspondence.kind == "interview"
    assert (
        applications.get_application("example_candidate", generated.application_id).state
        is ApplicationState.INTERVIEW
    )
    package = applications.prepare_interview("example_candidate", generated.application_id)
    assert package.exact_cv
    assert package.company == "Fictional Robotics Ltd"
    assert applications.list_notifications("example_candidate")[0].immediate
    assert "interview_package" in {
        artifact.kind
        for artifact in applications.list_artifacts("example_candidate", generated.application_id)
    }

    with pytest.raises(ApplicationConflictError, match="already consumed"):
        applications.submit_synthetic(
            "example_candidate",
            generated.application_id,
            SyntheticSubmissionRequest(
                authorization_id=authorization.authorization_id,
                synthetic_fixture_acknowledged=True,
                backend_confirmation_detected=True,
                confirmation_reference="synthetic-confirmation-duplicate",
            ),
            "submit-synthetic-duplicate",
        )


def test_captcha_creates_visible_resumable_human_action(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _lower_fixture_threshold(copied_candidates_root)
    jobs, applications, _sessions = _services(copied_candidates_root, tmp_path / "runtime")
    job_id = _job(jobs, 502)
    generated = applications.generate_materials(
        "example_candidate", job_id, "generate-materials-502"
    )
    applications.approve_materials(
        "example_candidate", generated.application_id, "approve-materials-502"
    )
    applications.start("example_candidate", generated.application_id, "start-application-502")

    blocked = applications.dry_run(
        "example_candidate",
        generated.application_id,
        DryRunCommand(challenge="captcha"),
        "dry-run-captcha-502",
    )
    assert blocked.state is ApplicationState.HUMAN_ACTION_REQUIRED
    actions = applications.list_human_actions("example_candidate")
    assert len(actions) == 1
    assert actions[0].kind == "captcha"
    assert actions[0].status == "pending"
    assert actions[0].browser_session_id is not None
    assert actions[0].screenshot_available

    completed = applications.complete_human_action(
        "example_candidate", actions[0].action_id, "complete-captcha-502"
    )
    assert completed.status == "completed"
    detail = applications.get_application("example_candidate", generated.application_id)
    assert detail.state is ApplicationState.READY_TO_SUBMIT


def test_unapproved_candidate_cannot_generate_materials(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    service = CandidateService(copied_candidates_root)
    service.create(
        CandidateCreateRequest(
            candidate_id="unapproved_candidate", display_name="Unapproved Candidate"
        )
    )
    _jobs, applications, _sessions = _services(copied_candidates_root, tmp_path / "runtime")

    with pytest.raises(ApplicationConflictError, match="candidate_profile"):
        applications.generate_materials(
            "unapproved_candidate",
            UUID("00000000-0000-0000-0000-000000000999"),
            "blocked-unapproved-generation",
        )


def test_settings_and_emergency_stop_are_hash_chained_in_admin_audit(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _jobs, applications, sessions = _services(copied_candidates_root, tmp_path / "runtime")
    applications.update_settings(
        SettingsUpdate(candidate_id="example_candidate", automation_mode="dry_run")
    )
    applications.emergency_stop("example_candidate")

    with sessions() as session:
        records = session.scalars(
            select(AdministrativeAuditRecord).order_by(AdministrativeAuditRecord.occurred_at)
        ).all()
        assert [record.event_type for record in records] == [
            "settings_updated",
            "emergency_stop_activated",
        ]
        assert records[0].previous_hash is None
        assert records[1].previous_hash == records[0].event_hash
