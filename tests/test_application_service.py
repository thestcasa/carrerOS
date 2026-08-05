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
from app.archive import ApplicationArchiveBuilder
from app.candidates.service import (
    CandidateCreateRequest,
    CandidateSectionUpdate,
    CandidateService,
)
from app.db import build_session_factory
from app.domain.enums import ApplicationState, DocumentKind
from app.domain.models import (
    AdministrativeAuditRecord,
    ApplicationArtifact,
    ApplicationDocument,
    ApplicationEvent,
    Base,
    BrowserSession,
    CandidateSettingsRecord,
    SecurityEvent,
)
from app.job_service import DiscoveryRequest, JobService


def _services(
    candidates_root: Path, runtime_root: Path, *, human_action_verified: bool = True
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
        ApplicationService(
            sessions,
            candidates,
            runtime_root,
            human_action_session_verifier=(
                lambda _candidate_id, _application_id, _session_id, _session_path: (
                    human_action_verified
                )
            ),
        ),
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
    jobs, applications, sessions = _services(copied_candidates_root, tmp_path / "runtime")
    job_id = _job(jobs)

    generated = applications.generate_materials(
        "example_candidate", job_id, "generate-materials-501"
    )
    assert (
        applications.generate_materials("example_candidate", job_id, "generate-materials-501")
        == generated
    )
    assert generated.state is ApplicationState.REVIEW_PENDING
    assert {document.kind for document in generated.documents} == {"cv", "cover_letter"}
    assert all(document.evidence_ids for document in generated.documents)
    assert generated.review is not None and generated.review.semantic_passed
    draft_artifacts = applications.list_artifacts("example_candidate", generated.application_id)
    rendered_cv = next(item for item in draft_artifacts if item.kind == "rendered_cv")
    rendered_cv_path = applications.artifact_path(
        "example_candidate", generated.application_id, rendered_cv.artifact_id
    )
    rendered_cv_bytes = rendered_cv_path.read_bytes()
    assert rendered_cv.metadata["valid"] is True
    assert rendered_cv.metadata["extraction_matches"] is True

    approved = applications.approve_materials(
        "example_candidate", generated.application_id, "approve-materials-501"
    )
    assert (
        applications.approve_materials(
            "example_candidate", generated.application_id, "approve-materials-501"
        )
        == approved
    )
    started = applications.start(
        "example_candidate", generated.application_id, "start-application-501"
    )
    assert (
        applications.start("example_candidate", generated.application_id, "start-application-501")
        == started
    )
    ready = applications.dry_run(
        "example_candidate",
        generated.application_id,
        DryRunCommand(),
        "dry-run-501",
    )
    assert ready.state is ApplicationState.READY_TO_SUBMIT
    assert (
        applications.dry_run(
            "example_candidate",
            generated.application_id,
            DryRunCommand(),
            "dry-run-501",
        )
        == ready
    )
    with pytest.raises(ApplicationConflictError, match="reused"):
        applications.dry_run(
            "example_candidate",
            generated.application_id,
            DryRunCommand(challenge="captcha"),
            "dry-run-501",
        )
    dry_run_event = next(
        event for event in ready.events if event.event_type == "FINAL_VALIDATION_STARTED"
    )
    final_page = dry_run_event.payload["final_page"]
    assert isinstance(final_page, dict)
    upload_hashes = final_page["upload_hashes"]
    assert isinstance(upload_hashes, list)
    assert rendered_cv.sha256 in upload_hashes

    authorization = applications.authorize(
        "example_candidate", generated.application_id, "authorize-application-501"
    )
    assert (
        applications.authorize(
            "example_candidate", generated.application_id, "authorize-application-501"
        )
        == authorization
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
    submitted_cv_bytes = applications.artifact_path(
        "example_candidate", generated.application_id, submitted_cv.artifact_id
    ).read_bytes()
    assert submitted_cv_bytes.startswith(b"%PDF-1.4")
    assert submitted_cv_bytes == rendered_cv_bytes
    assert submitted_cv.sha256 == rendered_cv.sha256
    result = applications.submit_synthetic(
        "example_candidate",
        generated.application_id,
        SyntheticSubmissionRequest(
            authorization_id=authorization.authorization_id,
            synthetic_fixture_acknowledged=True,
        ),
        "submit-synthetic-501",
    )

    assert result.successful
    assert result.state is ApplicationState.CONFIRMED
    with sessions() as session:
        browser_session = session.scalar(
            select(BrowserSession).where(
                BrowserSession.candidate_id == "example_candidate",
                BrowserSession.application_id == generated.application_id,
            )
        )
        assert browser_session is not None and browser_session.status == "confirmed"
    detail = applications.get_application("example_candidate", generated.application_id)
    assert detail.confirmation_reference == f"synthetic-confirmation-{generated.application_id}"
    assert detail.archive_available
    artifacts = applications.list_artifacts("example_candidate", generated.application_id)
    assert {
        "archive_manifest",
        "rendered_cv",
        "rendered_cover_letter",
        "render_report_cv",
        "render_report_cover_letter",
        "submitted_cv",
        "submitted_cover_letter",
        "submitted_answers",
        "submission_receipt",
    }.issubset({artifact.kind for artifact in artifacts})
    draft_kinds = {
        "rendered_cv",
        "rendered_cover_letter",
        "render_report_cv",
        "render_report_cover_letter",
    }
    assert all(not artifact.immutable for artifact in artifacts if artifact.kind in draft_kinds)
    assert all(artifact.immutable for artifact in artifacts if artifact.kind not in draft_kinds)
    final_receipt = next(
        artifact
        for artifact in artifacts
        if artifact.kind == "submission_receipt" and artifact.version == 2
    )
    final_archive = Path(str(final_receipt.metadata["archive_uri"]))
    pre_submit_archive = Path(str(final_receipt.metadata["pre_submit_archive_uri"]))
    archive_builder = ApplicationArchiveBuilder(tmp_path / "runtime" / "application_archive")
    assert archive_builder.verify(final_archive)
    assert archive_builder.verify(pre_submit_archive)
    receipt_payload = json.loads(
        applications.artifact_path(
            "example_candidate", generated.application_id, final_receipt.artifact_id
        ).read_text(encoding="utf-8")
    )
    assert receipt_payload["status"] == "confirmed"
    assert receipt_payload["confirmation_detected"] is True

    replay = applications.submit_synthetic(
        "example_candidate",
        generated.application_id,
        SyntheticSubmissionRequest(
            authorization_id=authorization.authorization_id,
            synthetic_fixture_acknowledged=True,
        ),
        "submit-synthetic-501",
    )
    assert replay == result

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
    replayed_correspondence = applications.ingest_correspondence(
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
    assert replayed_correspondence == correspondence
    with pytest.raises(ApplicationConflictError, match="reused"):
        applications.ingest_correspondence(
            CorrespondenceIngestRequest(
                candidate_id="example_candidate",
                provider_message_id="fictional-interview-501",
                sender="recruiting@fictional-robotics.invalid",
                recipients=("morgan@example.invalid",),
                subject="Changed fictional subject",
                body_text="Please schedule an interview for the Machine Learning Engineer role.",
                received_at=datetime(2026, 8, 5, 14, tzinfo=UTC),
            ),
            "correspondence-interview-501",
        )
    with pytest.raises(ApplicationConflictError, match="message ID was reused"):
        applications.ingest_correspondence(
            CorrespondenceIngestRequest(
                candidate_id="example_candidate",
                provider_message_id="fictional-interview-501",
                sender="recruiting@fictional-robotics.invalid",
                recipients=("morgan@example.invalid",),
                subject="Changed fictional subject",
                body_text="Please schedule an interview for the Machine Learning Engineer role.",
                received_at=datetime(2026, 8, 5, 14, tzinfo=UTC),
            ),
            "correspondence-changed-fresh-key",
        )
    assert correspondence.application_id == generated.application_id
    assert correspondence.kind == "interview"
    assert (
        applications.get_application("example_candidate", generated.application_id).state
        is ApplicationState.INTERVIEW
    )
    assert (
        applications.submit_synthetic(
            "example_candidate",
            generated.application_id,
            SyntheticSubmissionRequest(
                authorization_id=authorization.authorization_id,
                synthetic_fixture_acknowledged=True,
            ),
            "submit-synthetic-501",
        )
        == result
    )
    package = applications.prepare_interview(
        "example_candidate", generated.application_id, "prepare-interview-package"
    )
    replayed_package = applications.prepare_interview(
        "example_candidate", generated.application_id, "prepare-interview-package"
    )
    assert replayed_package == package
    with pytest.raises(ApplicationConflictError, match="reused with another request"):
        applications.prepare_interview(
            "example_candidate",
            UUID("00000000-0000-0000-0000-000000000999"),
            "prepare-interview-package",
        )
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
            ),
            "submit-synthetic-duplicate",
        )


def test_render_failure_is_persisted_and_cannot_be_approved(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _lower_fixture_threshold(copied_candidates_root)
    biography_path = copied_candidates_root / "example_candidate" / "biography.json"
    biography = json.loads(biography_path.read_text(encoding="utf-8"))
    biography["summary"] += " 🧪"
    biography_path.write_text(json.dumps(biography, ensure_ascii=False), encoding="utf-8")
    jobs, applications, _sessions = _services(copied_candidates_root, tmp_path / "runtime")

    generated = applications.generate_materials(
        "example_candidate", _job(jobs, 502), "generate-materials-502"
    )

    assert generated.state is ApplicationState.REVIEW_FAILED
    assert generated.review is not None and not generated.review.semantic_passed
    artifacts = applications.list_artifacts("example_candidate", generated.application_id)
    assert {item.kind for item in artifacts} == {
        "render_report_cv",
        "render_report_cover_letter",
    }
    assert all(item.metadata["valid"] is False for item in artifacts)
    with pytest.raises(ApplicationConflictError, match="did not pass"):
        applications.approve_materials(
            "example_candidate", generated.application_id, "approve-materials-502"
        )


def test_tampered_rendered_cv_is_rejected_before_browser_upload(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _lower_fixture_threshold(copied_candidates_root)
    jobs, applications, _sessions = _services(copied_candidates_root, tmp_path / "runtime")
    generated = applications.generate_materials(
        "example_candidate", _job(jobs, 503), "generate-materials-503"
    )
    applications.approve_materials(
        "example_candidate", generated.application_id, "approve-materials-503"
    )
    applications.start("example_candidate", generated.application_id, "start-503")
    rendered_cv = next(
        item
        for item in applications.list_artifacts("example_candidate", generated.application_id)
        if item.kind == "rendered_cv"
    )
    path = applications.artifact_path(
        "example_candidate", generated.application_id, rendered_cv.artifact_id
    )
    path.write_bytes(path.read_bytes() + b"tampered")

    with pytest.raises(ApplicationConflictError, match="rendered CV is missing or corrupted"):
        applications.dry_run(
            "example_candidate", generated.application_id, DryRunCommand(), "dry-run-503"
        )


def test_materials_can_be_regenerated_with_a_new_exact_snapshot_and_version(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _lower_fixture_threshold(copied_candidates_root)
    biography_path = copied_candidates_root / "example_candidate" / "biography.json"
    biography = json.loads(biography_path.read_text(encoding="utf-8"))
    biography["summary"] += " 🧪"
    biography_path.write_text(json.dumps(biography, ensure_ascii=False), encoding="utf-8")
    jobs, applications, _sessions = _services(copied_candidates_root, tmp_path / "runtime")
    job_id = _job(jobs, 505)

    failed = applications.generate_materials(
        "example_candidate", job_id, "generate-materials-505-invalid"
    )
    assert failed.state is ApplicationState.REVIEW_FAILED

    biography["summary"] = biography["summary"].removesuffix(" 🧪")
    CandidateService(copied_candidates_root).update_section(
        "example_candidate",
        CandidateSectionUpdate(section="biography", data=biography),
        "update-biography-regeneration",
    )
    regenerated = applications.generate_materials(
        "example_candidate", job_id, "generate-materials-505-valid"
    )

    assert regenerated.state is ApplicationState.REVIEW_PENDING
    assert {document.version for document in regenerated.documents} == {1, 2}
    latest_documents = {
        document.kind: document for document in regenerated.documents if document.version == 2
    }
    assert set(latest_documents) == {"cv", "cover_letter"}
    artifacts = applications.list_artifacts("example_candidate", regenerated.application_id)
    rendered_v2 = {
        item.kind: item
        for item in artifacts
        if item.kind.startswith("rendered_") and item.version == 2
    }
    assert set(rendered_v2) == {"rendered_cv", "rendered_cover_letter"}
    assert all(item.metadata["document_version"] == 2 for item in rendered_v2.values())
    assert len({item.metadata["candidate_snapshot_id"] for item in rendered_v2.values()}) == 1

    applications.approve_materials(
        "example_candidate", regenerated.application_id, "approve-materials-505"
    )
    applications.start("example_candidate", regenerated.application_id, "start-505")
    applications.dry_run(
        "example_candidate", regenerated.application_id, DryRunCommand(), "dry-run-505"
    )
    applications.authorize("example_candidate", regenerated.application_id, "authorize-505")
    submitted_cv = next(
        item
        for item in applications.list_artifacts("example_candidate", regenerated.application_id)
        if item.kind == "submitted_cv"
    )
    assert submitted_cv.sha256 == rendered_v2["rendered_cv"].sha256


def test_approval_revalidates_the_exact_reviewed_pdf(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _lower_fixture_threshold(copied_candidates_root)
    jobs, applications, _sessions = _services(copied_candidates_root, tmp_path / "runtime")
    generated = applications.generate_materials(
        "example_candidate", _job(jobs, 506), "generate-materials-506"
    )
    rendered_cv = next(
        item
        for item in applications.list_artifacts("example_candidate", generated.application_id)
        if item.kind == "rendered_cv"
    )
    path = applications.artifact_path(
        "example_candidate", generated.application_id, rendered_cv.artifact_id
    )
    path.write_bytes(path.read_bytes() + b"tampered")

    with pytest.raises(ApplicationConflictError, match="rendered CV is missing or corrupted"):
        applications.approve_materials(
            "example_candidate", generated.application_id, "approve-materials-506"
        )


def test_authorization_and_submission_reject_package_identity_drift(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _lower_fixture_threshold(copied_candidates_root)
    jobs, applications, sessions = _services(copied_candidates_root, tmp_path / "runtime")
    generated = applications.generate_materials(
        "example_candidate", _job(jobs, 507), "generate-materials-507"
    )
    applications.approve_materials(
        "example_candidate", generated.application_id, "approve-materials-507"
    )
    applications.start("example_candidate", generated.application_id, "start-507")
    applications.dry_run(
        "example_candidate", generated.application_id, DryRunCommand(), "dry-run-507"
    )

    with sessions.begin() as session:
        event_record = session.scalar(
            select(ApplicationEvent).where(
                ApplicationEvent.application_id == generated.application_id,
                ApplicationEvent.event_type == "FINAL_VALIDATION_STARTED",
            )
        )
        assert event_record is not None
        payload = dict(event_record.payload)
        final_page = dict(payload["final_page"])
        final_page["upload_hashes"] = ["0" * 64]
        payload["final_page"] = final_page
        event_record.payload = payload
    with pytest.raises(ApplicationConflictError, match="submission gate denied"):
        applications.authorize(
            "example_candidate", generated.application_id, "authorize-507-invalid"
        )

    rendered_cv = next(
        item
        for item in applications.list_artifacts("example_candidate", generated.application_id)
        if item.kind == "rendered_cv"
    )
    with sessions.begin() as session:
        event_record = session.scalar(
            select(ApplicationEvent).where(
                ApplicationEvent.application_id == generated.application_id,
                ApplicationEvent.event_type == "FINAL_VALIDATION_STARTED",
            )
        )
        assert event_record is not None
        payload = dict(event_record.payload)
        final_page = dict(payload["final_page"])
        final_page["upload_hashes"] = [rendered_cv.sha256]
        payload["final_page"] = final_page
        event_record.payload = payload
    authorization = applications.authorize(
        "example_candidate", generated.application_id, "authorize-507-valid"
    )
    with sessions() as session:
        artifact = session.scalar(
            select(ApplicationArtifact).where(
                ApplicationArtifact.application_id == generated.application_id,
                ApplicationArtifact.kind == "rendered_cv",
            )
        )
        assert artifact is not None
        rendered_path = Path(artifact.storage_uri)
        document = session.scalar(
            select(ApplicationDocument).where(
                ApplicationDocument.application_id == generated.application_id,
                ApplicationDocument.kind == DocumentKind.CV,
            )
        )
        assert document is not None
        source_path = Path(document.storage_uri)
    source_bytes = source_path.read_bytes()
    source_path.write_bytes(source_bytes + b"tampered")

    with pytest.raises(ApplicationConflictError, match="reviewed CV source"):
        applications.submit_synthetic(
            "example_candidate",
            generated.application_id,
            SyntheticSubmissionRequest(
                authorization_id=authorization.authorization_id,
                synthetic_fixture_acknowledged=True,
            ),
            "submit-507-source-tamper",
        )

    source_path.write_bytes(source_bytes)
    rendered_path.write_bytes(rendered_path.read_bytes() + b"tampered")

    with pytest.raises(ApplicationConflictError, match="rendered CV is missing or corrupted"):
        applications.submit_synthetic(
            "example_candidate",
            generated.application_id,
            SyntheticSubmissionRequest(
                authorization_id=authorization.authorization_id,
                synthetic_fixture_acknowledged=True,
            ),
            "submit-507",
        )


def test_candidate_artifact_symlink_cannot_cross_candidate_scope(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _lower_fixture_threshold(copied_candidates_root)
    runtime_root = tmp_path / "runtime"
    jobs, applications, _sessions = _services(copied_candidates_root, runtime_root)
    job_id = _job(jobs, 508)
    beta_root = runtime_root / "candidates" / "candidate_beta"
    beta_root.mkdir(parents=True)
    sentinel = beta_root / "sentinel.txt"
    sentinel.write_text("candidate beta", encoding="utf-8")
    (runtime_root / "candidates" / "example_candidate").symlink_to(
        beta_root, target_is_directory=True
    )

    with pytest.raises(ApplicationConflictError, match="contains a symlink"):
        applications.generate_materials("example_candidate", job_id, "generate-materials-508")
    assert sentinel.read_text(encoding="utf-8") == "candidate beta"
    assert tuple(beta_root.iterdir()) == (sentinel,)


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

    with pytest.raises(ApplicationConflictError, match="open the recoverable browser session"):
        applications.complete_human_action(
            "example_candidate", actions[0].action_id, "complete-before-open-captcha-502"
        )
    opened = applications.open_human_session(
        "example_candidate", actions[0].action_id, "open-captcha-502"
    )
    assert opened.session_opened
    assert (
        applications.open_human_session(
            "example_candidate", actions[0].action_id, "open-captcha-502"
        )
        == opened
    )
    completed = applications.complete_human_action(
        "example_candidate", actions[0].action_id, "complete-captcha-502"
    )
    assert completed.status == "completed"
    assert (
        applications.complete_human_action(
            "example_candidate", actions[0].action_id, "complete-captcha-502"
        )
        == completed
    )
    with pytest.raises(ApplicationConflictError, match="reused"):
        applications.complete_human_action(
            "example_candidate",
            actions[0].action_id,
            "complete-captcha-502",
            cancel=True,
        )
    with pytest.raises(ApplicationConflictError, match="already completed"):
        applications.complete_human_action(
            "example_candidate",
            actions[0].action_id,
            "cancel-completed-captcha-fresh-key",
            cancel=True,
        )
    detail = applications.get_application("example_candidate", generated.application_id)
    assert detail.state is ApplicationState.READY_TO_SUBMIT


def test_captcha_completion_fails_closed_without_same_session_verification(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _lower_fixture_threshold(copied_candidates_root)
    jobs, applications, _sessions = _services(
        copied_candidates_root,
        tmp_path / "runtime",
        human_action_verified=False,
    )
    job_id = _job(jobs, 503)
    generated = applications.generate_materials(
        "example_candidate", job_id, "generate-materials-503"
    )
    applications.approve_materials(
        "example_candidate", generated.application_id, "approve-materials-503"
    )
    applications.start("example_candidate", generated.application_id, "start-application-503")
    applications.dry_run(
        "example_candidate",
        generated.application_id,
        DryRunCommand(challenge="captcha"),
        "dry-run-captcha-503",
    )
    action = applications.list_human_actions("example_candidate")[0]
    applications.open_human_session("example_candidate", action.action_id, "open-captcha-503")

    with pytest.raises(ApplicationConflictError, match="has not verified"):
        applications.complete_human_action(
            "example_candidate", action.action_id, "complete-captcha-503"
        )

    detail = applications.get_application("example_candidate", generated.application_id)
    assert detail.state is ApplicationState.HUMAN_ACTION_REQUIRED
    assert applications.list_human_actions("example_candidate")[0].status == "pending"


def test_denied_authorization_does_not_seal_an_orphan_archive(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _lower_fixture_threshold(copied_candidates_root)
    jobs, applications, _sessions = _services(copied_candidates_root, tmp_path / "runtime")
    job_id = _job(jobs, 504)
    generated = applications.generate_materials(
        "example_candidate", job_id, "generate-materials-504"
    )

    with pytest.raises(ApplicationConflictError, match="submission gate denied"):
        applications.authorize(
            "example_candidate", generated.application_id, "authorize-too-early-504"
        )

    archive_root = tmp_path / "runtime" / "application_archive"
    assert not archive_root.exists() or not any(archive_root.rglob("manifest.json"))


def test_unapproved_candidate_cannot_generate_materials(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    service = CandidateService(copied_candidates_root)
    service.create(
        CandidateCreateRequest(
            candidate_id="unapproved_candidate", display_name="Unapproved Candidate"
        ),
        "create-unapproved-candidate",
    )
    _jobs, applications, _sessions = _services(copied_candidates_root, tmp_path / "runtime")

    with pytest.raises(ApplicationConflictError, match="candidate_profile"):
        applications.generate_materials(
            "unapproved_candidate",
            UUID("00000000-0000-0000-0000-000000000999"),
            "blocked-unapproved-generation",
        )


def test_generation_excludes_unapproved_internal_and_unverified_facts(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _lower_fixture_threshold(copied_candidates_root)
    experience_path = copied_candidates_root / "example_candidate" / "experience.json"
    experience = json.loads(experience_path.read_text(encoding="utf-8"))
    experience["items"][0]["achievements"].extend(
        [
            {
                "id": "internal_secret_claim",
                "statement": "INTERNAL SECRET MUST NOT LEAVE",
                "verified": True,
                "source": "internal fixture",
                "publicly_usable": True,
                "confidentiality": "internal",
                "approved": True,
                "archived": False,
            },
            {
                "id": "unapproved_public_claim",
                "statement": "UNAPPROVED CLAIM MUST NOT LEAVE",
                "verified": True,
                "source": "public fixture",
                "publicly_usable": True,
                "confidentiality": "public",
                "approved": False,
                "archived": False,
            },
            {
                "id": "unverified_public_claim",
                "statement": "UNVERIFIED CLAIM MUST NOT LEAVE",
                "verified": False,
                "source": "public fixture",
                "publicly_usable": True,
                "confidentiality": "public",
                "approved": False,
                "archived": False,
            },
        ]
    )
    experience_path.write_text(json.dumps(experience), encoding="utf-8")
    jobs, applications, _sessions = _services(copied_candidates_root, tmp_path / "runtime")
    job_id = _job(jobs, 503)

    generated = applications.generate_materials(
        "example_candidate", job_id, "generate-materials-503"
    )
    content = "\n".join(document.content for document in generated.documents)

    assert "Introduced typed API contracts" in content
    assert "INTERNAL SECRET MUST NOT LEAVE" not in content
    assert "UNAPPROVED CLAIM MUST NOT LEAVE" not in content
    assert "UNVERIFIED CLAIM MUST NOT LEAVE" not in content


def test_settings_and_emergency_stop_are_hash_chained_in_admin_audit(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _jobs, applications, sessions = _services(copied_candidates_root, tmp_path / "runtime")
    applications.update_settings(
        SettingsUpdate(candidate_id="example_candidate", automation_mode="dry_run"),
        "settings-update-audit",
    )
    applications.emergency_stop("example_candidate", "emergency-stop-audit")

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


def test_reading_default_settings_does_not_mutate_persistence(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _jobs, applications, sessions = _services(copied_candidates_root, tmp_path / "runtime")

    settings = applications.get_settings("example_candidate")

    assert settings.candidate_id == "example_candidate"
    with sessions() as session:
        assert session.scalars(select(CandidateSettingsRecord)).all() == []


def test_settings_commands_are_payload_bound_and_replay_without_duplicate_audit(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _jobs, applications, sessions = _services(copied_candidates_root, tmp_path / "runtime")
    command = SettingsUpdate(candidate_id="example_candidate", discovery_enabled=True)

    first = applications.update_settings(command, "settings-replay-key")
    replay = applications.update_settings(command, "settings-replay-key")

    assert replay == first
    with pytest.raises(ApplicationConflictError, match="reused with another request"):
        applications.update_settings(
            SettingsUpdate(candidate_id="example_candidate", discovery_enabled=False),
            "settings-replay-key",
        )
    with sessions() as session:
        records = session.scalars(select(AdministrativeAuditRecord)).all()
        assert [record.event_type for record in records] == ["settings_updated"]


def test_security_resolution_is_payload_bound_and_replays_without_duplicate_audit(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _jobs, applications, sessions = _services(copied_candidates_root, tmp_path / "runtime")
    with sessions.begin() as session:
        finding = SecurityEvent(
            candidate_id="example_candidate",
            category="prompt_injection",
            severity="high",
            details={"reason": "fictional test finding"},
        )
        session.add(finding)
        session.flush()
        finding_id = finding.id

    first = applications.resolve_security_event(
        "example_candidate", finding_id, "resolve-security-finding"
    )
    replay = applications.resolve_security_event(
        "example_candidate", finding_id, "resolve-security-finding"
    )

    assert replay == first
    assert first.resolved
    with pytest.raises(ApplicationConflictError, match="reused with another request"):
        applications.resolve_security_event(
            "example_candidate",
            UUID("00000000-0000-0000-0000-000000000999"),
            "resolve-security-finding",
        )
    with sessions() as session:
        records = session.scalars(select(AdministrativeAuditRecord)).all()
        assert [record.event_type for record in records] == ["security_event_resolved"]
