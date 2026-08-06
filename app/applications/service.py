from __future__ import annotations

import hashlib
import hmac
import json
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.applications.contracts import (
    AnalyticsOverview,
    AnswerView,
    ApplicationDetail,
    ApplicationSummary,
    ArtifactView,
    AuthorizationView,
    CorrespondenceIngestRequest,
    CorrespondenceView,
    DocumentView,
    DryRunCommand,
    EventView,
    HumanActionView,
    NotificationView,
    ReviewView,
    SecurityEventView,
    SettingsUpdate,
    SettingsView,
    SubmissionResultView,
    SyntheticSubmissionRequest,
)
from app.archive import (
    ApplicationArchiveBuilder,
    ApplicationArchiveData,
    ArchiveManifest,
    canonical_json_bytes,
    sha256_bytes,
)
from app.browser import DryRunRequest, FieldKind, SyntheticBrowserDryRunner, UploadArtifact
from app.browser.fixtures import standard_application_form
from app.candidates.models import CandidateConfig, ClaimFact
from app.candidates.service import CandidateService
from app.candidates.snapshot import CandidateSnapshot
from app.correspondence import (
    ApplicationReference,
    ArchivedApplicationArtifacts,
    CorrespondenceKind,
    CorrespondenceService,
    InterviewPreparationPackage,
    MessageFixture,
    SubmittedAnswer,
)
from app.discovery.deduplication import application_duplicate_hash, submission_identity_hash
from app.discovery.verification import (
    JobSourceVerifier,
    ProviderJobSourceVerifier,
    VerificationEvidence,
    apply_verification,
)
from app.domain.enums import (
    ApplicationOutcome,
    ApplicationState,
    DocumentKind,
    HumanActionKind,
)
from app.domain.models import (
    AdministrativeAuditRecord,
    AdministrativeCommandReceipt,
    AgentReview,
    Application,
    ApplicationAnswer,
    ApplicationArtifact,
    ApplicationDocument,
    ApplicationEvent,
    BrowserSession,
    CandidateJobScore,
    CandidateSettingsRecord,
    CandidateSnapshotRecord,
    GlobalJob,
    HumanAction,
    NotificationRecord,
    SecurityEvent,
    SubmissionAuthorizationRecord,
)
from app.domain.models import CorrespondenceRecord as StoredCorrespondence
from app.materials import (
    DeterministicMaterialGenerator,
    DeterministicPdfRenderer,
    IndependentMaterialReviewer,
    template_for,
)
from app.materials.contracts import (
    AnswerPrompt,
    ApprovedAnswerFact,
    ApprovedFact,
    GenerationRequest,
    JobTarget,
    MaterialReview,
)
from app.operations import AuthorizationConsumer
from app.submission_gate import SubmissionGate, SubmissionGateInput
from app.workflow import VALID_TRANSITIONS


class ApplicationServiceError(ValueError):
    pass


class ApplicationNotFoundError(ApplicationServiceError):
    pass


class ApplicationConflictError(ApplicationServiceError):
    pass


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class ApplicationService:
    """Candidate-scoped integration boundary for materials, dry runs, and application history."""

    _GENERATION_FRESHNESS = timedelta(hours=24)
    _SUBMISSION_FRESHNESS = timedelta(minutes=15)

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        candidate_service: CandidateService,
        runtime_root: Path,
        synthetic_confirmation: Callable[[str, UUID], str | None] | None = None,
        human_action_session_verifier: Callable[[str, UUID, UUID, Path], bool] | None = None,
        source_verifier: JobSourceVerifier | None = None,
    ) -> None:
        self._sessions = session_factory
        self._candidates = candidate_service
        self._runtime_root = runtime_root.resolve()
        self._generator = DeterministicMaterialGenerator()
        self._renderer = DeterministicPdfRenderer()
        self._reviewer = IndependentMaterialReviewer()
        self._browser = SyntheticBrowserDryRunner(self._runtime_root)
        self._archives = ApplicationArchiveBuilder(self._runtime_root / "application_archive")
        self._consumer = AuthorizationConsumer(session_factory)
        self._correspondence = CorrespondenceService()
        self._source_verifier = source_verifier or ProviderJobSourceVerifier()
        self._synthetic_confirmation = synthetic_confirmation or (
            lambda _candidate_id, application_id: f"synthetic-confirmation-{application_id}"
        )
        self._human_action_session_verifier = human_action_session_verifier or (
            lambda _candidate_id, _application_id, _session_id, _session_path: False
        )

    def list_applications(self, candidate_id: str) -> tuple[ApplicationSummary, ...]:
        self._candidates.get_config(candidate_id)
        with self._sessions() as session:
            applications = session.scalars(
                select(Application)
                .where(Application.candidate_id == candidate_id)
                .order_by(Application.updated_at.desc())
            ).all()
            return tuple(self._summary(session, item) for item in applications)

    def get_application(self, candidate_id: str, application_id: UUID) -> ApplicationDetail:
        self._candidates.get_config(candidate_id)
        with self._sessions() as session:
            application = self._application(session, candidate_id, application_id)
            return self._detail(session, application)

    def generate_materials(
        self,
        candidate_id: str,
        job_id: UUID,
        idempotency_key: str,
    ) -> ApplicationDetail:
        with self._candidates.lifecycle_write(candidate_id):
            return self._generate_materials(candidate_id, job_id, idempotency_key)

    def _generate_materials(
        self,
        candidate_id: str,
        job_id: UUID,
        idempotency_key: str,
    ) -> ApplicationDetail:
        payload = {"job_id": str(job_id)}
        with self._sessions() as lookup:
            replay, _, _ = self._administrative_command_replay(
                lookup, candidate_id, "generate_materials", payload, idempotency_key
            )
            if replay is not None:
                return ApplicationDetail.model_validate(replay)
        config = self._candidates.get_config(candidate_id)
        generation_blockers = [
            name
            for name, approved in {
                "candidate_profile": config.manifest.validation.profile_approved,
                "legal_status": config.manifest.validation.legal_status_approved,
                "automatic_answers": config.manifest.validation.automatic_answers_approved,
                "cv_templates": config.manifest.validation.cv_templates_approved,
            }.items()
            if not approved
        ]
        if generation_blockers:
            raise ApplicationConflictError(
                "material generation requires approved " + ", ".join(generation_blockers)
            )
        self._revalidate_job(job_id)
        with self._sessions.begin() as session:
            replay, request_sha256, key_sha256 = self._administrative_command_replay(
                session, candidate_id, "generate_materials", payload, idempotency_key
            )
            if replay is not None:
                return ApplicationDetail.model_validate(replay)
            job = session.get(GlobalJob, job_id)
            if job is None:
                raise ApplicationNotFoundError(f"job not found: {job_id}")
            if not self._job_is_fresh(job, datetime.now(UTC), self._GENERATION_FRESHNESS):
                raise ApplicationConflictError(
                    "job must be revalidated from its source before material generation"
                )
            duplicate_hash = application_duplicate_hash(
                candidate_id=candidate_id,
                company=job.company,
                title=job.normalized_title or job.title,
                location=job.normalized_location or job.location,
                requisition_id=job.requisition_id,
            )
            identity_hash = submission_identity_hash(
                candidate_id=candidate_id,
                company=job.company,
                title=job.normalized_title or job.title,
                location=job.normalized_location or job.location,
                requisition_id=job.requisition_id,
                application_url=job.application_url,
            )
            score = session.scalar(
                select(CandidateJobScore)
                .where(
                    CandidateJobScore.candidate_id == candidate_id,
                    CandidateJobScore.job_id == job_id,
                )
                .order_by(CandidateJobScore.scoring_version.desc())
                .limit(1)
            )
            if score is None:
                raise ApplicationConflictError("job must be analyzed before material generation")
            application = session.scalar(
                select(Application).where(
                    Application.candidate_id == candidate_id,
                    Application.job_id == job_id,
                )
            )
            duplicate_application = session.scalar(
                select(Application).where(
                    Application.candidate_id == candidate_id,
                    Application.submission_identity_hash == identity_hash,
                    Application.job_id != job_id,
                )
            )
            if duplicate_application is not None:
                raise ApplicationConflictError(
                    "candidate already has an application for this requisition or equivalent job"
                )
            if application is None:
                application = Application(
                    candidate_id=candidate_id,
                    job_id=job_id,
                    score_id=score.id,
                    duplicate_hash=duplicate_hash,
                    submission_identity_hash=identity_hash,
                    state=ApplicationState.SHORTLISTED,
                )
                session.add(application)
                session.flush()
                session.add(
                    ApplicationEvent(
                        candidate_id=candidate_id,
                        application_id=application.id,
                        idempotency_key=f"{idempotency_key}:shortlist",
                        event_type="JOB_SHORTLISTED",
                        from_state=ApplicationState.SCORED,
                        to_state=ApplicationState.SHORTLISTED,
                    )
                )
            else:
                if application.duplicate_hash is None:
                    application.duplicate_hash = duplicate_hash
                if application.submission_identity_hash is None:
                    application.submission_identity_hash = identity_hash
            event_replay = session.scalar(
                select(ApplicationEvent).where(
                    ApplicationEvent.candidate_id == candidate_id,
                    ApplicationEvent.application_id == application.id,
                    ApplicationEvent.idempotency_key == f"{idempotency_key}:review",
                )
            )
            if event_replay is not None:
                view = self._detail(session, application)
                self._append_administrative_command_receipt(
                    session,
                    candidate_id,
                    "generate_materials",
                    key_sha256,
                    request_sha256,
                    view.model_dump(mode="json"),
                )
                return view

            snapshot_record = session.scalar(
                select(CandidateSnapshotRecord).where(
                    CandidateSnapshotRecord.candidate_id == candidate_id,
                    CandidateSnapshotRecord.application_id == application.id,
                    CandidateSnapshotRecord.profile_version == config.manifest.profile_version,
                )
            )
            if snapshot_record is None:
                snapshot = self._candidates.snapshot(candidate_id)
                snapshot_path = self._write_exclusive(
                    candidate_id,
                    application.id,
                    "candidate_snapshot",
                    f"{snapshot.config_sha256}.json",
                    canonical_json_bytes(snapshot.model_dump(mode="json")),
                )
                snapshot_record = CandidateSnapshotRecord(
                    id=snapshot.snapshot_id,
                    candidate_id=candidate_id,
                    application_id=application.id,
                    profile_version=snapshot.profile_version,
                    sha256=snapshot.config_sha256,
                    storage_uri=str(snapshot_path),
                )
                session.add(snapshot_record)
            else:
                snapshot = self._load_candidate_snapshot(application, snapshot_record)
            regenerating = application.state is ApplicationState.REVIEW_FAILED
            if application.state is ApplicationState.SHORTLISTED:
                self._transition(
                    session,
                    application,
                    ApplicationState.CANDIDATE_SNAPSHOT_CREATED,
                    f"{idempotency_key}:snapshot",
                    "CANDIDATE_SNAPSHOT_CREATED",
                )
            elif application.state is not ApplicationState.REVIEW_FAILED:
                raise ApplicationConflictError("application is not ready for material generation")
            self._transition(
                session,
                application,
                ApplicationState.MATERIALS_GENERATING,
                f"{idempotency_key}:generating",
                "MATERIALS_REGENERATION_STARTED"
                if regenerating
                else "MATERIALS_GENERATION_STARTED",
            )
            request = self._generation_request(config, application.id, job)
            generated = self._generator.generate(request)
            document_versions = {
                document.kind: (
                    session.scalar(
                        select(func.max(ApplicationDocument.version)).where(
                            ApplicationDocument.candidate_id == candidate_id,
                            ApplicationDocument.application_id == application.id,
                            ApplicationDocument.kind == document.kind,
                        )
                    )
                    or 0
                )
                + 1
                for document in generated.documents
            }
            rendered = tuple(
                self._renderer.render(
                    document,
                    template_id=template_for(
                        document.kind,
                        config.cv_rules.template_id,
                        config.cv_rules.template_version,
                    )[0],
                    template_version=template_for(
                        document.kind,
                        config.cv_rules.template_id,
                        config.cv_rules.template_version,
                    )[1],
                    maximum_pages=(
                        config.cv_rules.max_pages if document.kind is DocumentKind.CV else 2
                    ),
                    document_version=document_versions[document.kind],
                )
                for document in generated.documents
            )
            review = self._reviewer.review(
                request, generated, tuple(item.report for item in rendered)
            )
            for rendered_document in rendered:
                document = rendered_document.document
                version = document_versions[document.kind]
                document_path = self._write_exclusive(
                    candidate_id,
                    application.id,
                    document.kind.value,
                    f"v{version}.txt",
                    document.content.encode("utf-8"),
                )
                evidence_ids = sorted(
                    {evidence for claim in document.claims for evidence in claim.evidence_ids}
                )
                session.add(
                    ApplicationDocument(
                        candidate_id=candidate_id,
                        application_id=application.id,
                        kind=document.kind,
                        version=version,
                        storage_uri=str(document_path),
                        sha256=document.content_sha256,
                        evidence_ids={"items": evidence_ids},
                        validated=review.documents_supported and rendered_document.report.valid,
                    )
                )
                render_metadata = {
                    **rendered_document.report.model_dump(mode="json"),
                    "candidate_snapshot_version": snapshot.profile_version,
                    "candidate_snapshot_sha256": snapshot.config_sha256,
                    "candidate_snapshot_id": str(snapshot.snapshot_id),
                    "document_version": version,
                    "evidence_ids": evidence_ids,
                }
                report_content = canonical_json_bytes(render_metadata)
                report_path = self._write_exclusive(
                    candidate_id,
                    application.id,
                    f"render_report_{document.kind.value}",
                    f"v{version}.json",
                    report_content,
                )
                session.add(
                    ApplicationArtifact(
                        candidate_id=candidate_id,
                        application_id=application.id,
                        kind=f"render_report_{document.kind.value}",
                        version=version,
                        storage_uri=str(report_path),
                        sha256=hashlib.sha256(report_content).hexdigest(),
                        content_type="application/json",
                        immutable=False,
                        artifact_metadata=render_metadata,
                    )
                )
                if rendered_document.report.valid:
                    pdf_path = self._write_exclusive(
                        candidate_id,
                        application.id,
                        f"rendered_{document.kind.value}",
                        f"v{version}.pdf",
                        rendered_document.pdf_bytes,
                    )
                    session.add(
                        ApplicationArtifact(
                            candidate_id=candidate_id,
                            application_id=application.id,
                            kind=f"rendered_{document.kind.value}",
                            version=version,
                            storage_uri=str(pdf_path),
                            sha256=rendered_document.report.pdf_sha256 or "",
                            content_type="application/pdf",
                            immutable=False,
                            artifact_metadata=render_metadata,
                        )
                    )
            for answer in generated.answers:
                stored_answer = session.scalar(
                    select(ApplicationAnswer).where(
                        ApplicationAnswer.candidate_id == candidate_id,
                        ApplicationAnswer.application_id == application.id,
                        ApplicationAnswer.question_key == answer.question_key,
                    )
                )
                if stored_answer is None:
                    stored_answer = ApplicationAnswer(
                        candidate_id=candidate_id,
                        application_id=application.id,
                        question_key=answer.question_key,
                        question=answer.question,
                        answer=answer.answer,
                    )
                    session.add(stored_answer)
                stored_answer.question = answer.question
                stored_answer.answer = answer.answer
                stored_answer.approved_source_key = answer.approved_source_key
                stored_answer.evidence_ids = {"items": list(answer.evidence_ids)}
                stored_answer.supported = answer.supported
            session.add(
                AgentReview(
                    candidate_id=candidate_id,
                    application_id=application.id,
                    decision=review.decision,
                    semantic_passed=review.semantic_review_passed,
                    report=review.model_dump(mode="json"),
                )
            )
            self._transition(
                session,
                application,
                ApplicationState.MATERIALS_READY,
                f"{idempotency_key}:ready",
                "MATERIALS_READY",
            )
            self._transition(
                session,
                application,
                ApplicationState.REVIEW_PENDING,
                f"{idempotency_key}:review",
                "INDEPENDENT_REVIEW_PASSED"
                if review.semantic_review_passed
                else "INDEPENDENT_REVIEW_COMPLETED",
                payload=review.model_dump(mode="json"),
            )
            if not review.semantic_review_passed:
                self._transition(
                    session,
                    application,
                    ApplicationState.REVIEW_FAILED,
                    f"{idempotency_key}:review-failed",
                    "INDEPENDENT_REVIEW_FAILED",
                    payload=review.model_dump(mode="json"),
                )
            session.flush()
            view = self._detail(session, application)
            self._append_administrative_command_receipt(
                session,
                candidate_id,
                "generate_materials",
                key_sha256,
                request_sha256,
                view.model_dump(mode="json"),
            )
            return view

    def approve_materials(
        self, candidate_id: str, application_id: UUID, idempotency_key: str
    ) -> ApplicationDetail:
        with self._candidates.lifecycle_write(candidate_id), self._sessions.begin() as session:
            payload = {"application_id": str(application_id)}
            replay, request_sha256, key_sha256 = self._administrative_command_replay(
                session, candidate_id, "approve_materials", payload, idempotency_key
            )
            if replay is not None:
                return ApplicationDetail.model_validate(replay)
            application = self._application(session, candidate_id, application_id)
            review = session.scalar(
                select(AgentReview)
                .where(
                    AgentReview.candidate_id == candidate_id,
                    AgentReview.application_id == application_id,
                )
                .order_by(AgentReview.created_at.desc())
                .limit(1)
            )
            if review is None:
                raise ApplicationConflictError("materials did not pass independent review")
            self._reviewed_materials(session, application, review)
            self._transition(
                session,
                application,
                ApplicationState.APPLICATION_STARTED,
                idempotency_key,
                "MATERIALS_APPROVED",
            )
            session.flush()
            view = self._detail(session, application)
            self._append_administrative_command_receipt(
                session,
                candidate_id,
                "approve_materials",
                key_sha256,
                request_sha256,
                view.model_dump(mode="json"),
            )
            return view

    def start(
        self, candidate_id: str, application_id: UUID, idempotency_key: str
    ) -> ApplicationDetail:
        with self._candidates.lifecycle_write(candidate_id), self._sessions.begin() as session:
            payload = {"application_id": str(application_id)}
            replay, request_sha256, key_sha256 = self._administrative_command_replay(
                session, candidate_id, "start_application", payload, idempotency_key
            )
            if replay is not None:
                return ApplicationDetail.model_validate(replay)
            application = self._application(session, candidate_id, application_id)
            self._transition(
                session,
                application,
                ApplicationState.FORM_FILLING,
                idempotency_key,
                "FORM_FILL_STARTED",
            )
            existing = session.scalar(
                select(BrowserSession).where(
                    BrowserSession.candidate_id == candidate_id,
                    BrowserSession.application_id == application_id,
                )
            )
            if existing is None:
                session.add(
                    BrowserSession(
                        candidate_id=candidate_id,
                        application_id=application_id,
                        status="synthetic_ready",
                    )
                )
            session.flush()
            view = self._detail(session, application)
            self._append_administrative_command_receipt(
                session,
                candidate_id,
                "start_application",
                key_sha256,
                request_sha256,
                view.model_dump(mode="json"),
            )
            return view

    def dry_run(
        self,
        candidate_id: str,
        application_id: UUID,
        command: DryRunCommand,
        idempotency_key: str,
    ) -> ApplicationDetail:
        with self._candidates.lifecycle_write(candidate_id):
            return self._dry_run(candidate_id, application_id, command, idempotency_key)

    def _dry_run(
        self,
        candidate_id: str,
        application_id: UUID,
        command: DryRunCommand,
        idempotency_key: str,
    ) -> ApplicationDetail:
        config = self._candidates.get_config(candidate_id)
        with self._sessions.begin() as session:
            payload = {
                "application_id": str(application_id),
                "command": command.model_dump(mode="json"),
            }
            replay, request_sha256, key_sha256 = self._administrative_command_replay(
                session, candidate_id, "dry_run_application", payload, idempotency_key
            )
            if replay is not None:
                return ApplicationDetail.model_validate(replay)
            application = self._application(session, candidate_id, application_id)
            if application.state is not ApplicationState.FORM_FILLING:
                raise ApplicationConflictError("application is not ready for form filling")
            review = session.scalar(
                select(AgentReview)
                .where(
                    AgentReview.candidate_id == candidate_id,
                    AgentReview.application_id == application_id,
                )
                .order_by(AgentReview.created_at.desc())
                .limit(1)
            )
            if review is None:
                raise ApplicationConflictError("validated rendered CV is missing or corrupted")
            reviewed_materials = self._reviewed_materials(session, application, review)
            rendered_cv = next(
                (
                    artifact
                    for document, artifact in reviewed_materials
                    if document.kind is DocumentKind.CV
                ),
                None,
            )
            if rendered_cv is None:
                raise ApplicationConflictError("validated rendered CV is missing or corrupted")
            browser_session = session.scalar(
                select(BrowserSession).where(
                    BrowserSession.candidate_id == candidate_id,
                    BrowserSession.application_id == application_id,
                )
            )
            if browser_session is None:
                raise ApplicationConflictError("browser session is missing")
            challenge = FieldKind(command.challenge) if command.challenge else None
            result = self._browser.run(
                DryRunRequest(
                    application_id=application_id,
                    candidate_id=candidate_id,
                    session_id=browser_session.id,
                    form=standard_application_form(challenge=challenge),
                    answers={
                        "first_name": config.identity.full_name.split()[0],
                        "email": config.identity.email,
                    },
                    uploads=(
                        UploadArtifact(
                            field_key="cv",
                            path=Path(rendered_cv.storage_uri),
                            sha256=rendered_cv.sha256,
                        ),
                    ),
                    allowed_upload_sha256=frozenset({rendered_cv.sha256}),
                )
            )
            browser_session.status = "human_action_required" if result.human_actions else "ready"
            browser_session.external_session_ref = str(result.session_directory)
            event_payload = result.model_dump(mode="json")
            if result.human_actions:
                action_result = result.human_actions[0]
                action = HumanAction(
                    candidate_id=candidate_id,
                    application_id=application_id,
                    actor_id="system",
                    action=HumanActionKind.PAUSE,
                    kind=action_result.reason.value,
                    reason=action_result.message,
                    payload=event_payload,
                    browser_session_id=browser_session.id,
                    screenshot_uri=str(result.screenshot_path),
                    expires_at=datetime.now(UTC) + timedelta(minutes=15),
                )
                session.add(action)
                self._transition(
                    session,
                    application,
                    ApplicationState.HUMAN_ACTION_REQUIRED,
                    idempotency_key,
                    "HUMAN_ACTION_REQUIRED",
                    payload=event_payload,
                )
            else:
                self._transition(
                    session,
                    application,
                    ApplicationState.FINAL_VALIDATION,
                    f"{idempotency_key}:validation",
                    "FINAL_VALIDATION_STARTED",
                    payload=event_payload,
                )
                self._transition(
                    session,
                    application,
                    ApplicationState.READY_TO_SUBMIT,
                    f"{idempotency_key}:ready",
                    "FINAL_VALIDATION_PASSED",
                    payload={"synthetic_only": True},
                )
            session.flush()
            view = self._detail(session, application)
            self._append_administrative_command_receipt(
                session,
                candidate_id,
                "dry_run_application",
                key_sha256,
                request_sha256,
                view.model_dump(mode="json"),
            )
            return view

    def authorize(
        self, candidate_id: str, application_id: UUID, idempotency_key: str
    ) -> AuthorizationView:
        with self._candidates.lifecycle_write(candidate_id):
            return self._authorize(candidate_id, application_id, idempotency_key)

    def _authorize(
        self, candidate_id: str, application_id: UUID, idempotency_key: str
    ) -> AuthorizationView:
        payload = {"application_id": str(application_id)}
        with self._sessions() as lookup:
            replay, _, _ = self._administrative_command_replay(
                lookup, candidate_id, "authorize_application", payload, idempotency_key
            )
            if replay is not None:
                return AuthorizationView.model_validate(replay)
            application = self._application(lookup, candidate_id, application_id)
            job_id = application.job_id
        self._revalidate_job(job_id)
        config = self._candidates.get_config(candidate_id)
        with self._sessions.begin() as session:
            replay, request_sha256, key_sha256 = self._administrative_command_replay(
                session, candidate_id, "authorize_application", payload, idempotency_key
            )
            if replay is not None:
                return AuthorizationView.model_validate(replay)
            application = self._application(session, candidate_id, application_id)
            existing = session.scalar(
                select(SubmissionAuthorizationRecord)
                .where(
                    SubmissionAuthorizationRecord.candidate_id == candidate_id,
                    SubmissionAuthorizationRecord.application_id == application_id,
                    SubmissionAuthorizationRecord.consumed_at.is_(None),
                )
                .order_by(SubmissionAuthorizationRecord.issued_at.desc())
                .limit(1)
            )
            now = datetime.now(UTC)
            settings = self._settings_record(session, candidate_id)
            if settings.emergency_stopped:
                raise ApplicationConflictError("emergency stop is active")
            job = session.get(GlobalJob, application.job_id)
            score = (
                session.get(CandidateJobScore, application.score_id)
                if application.score_id
                else None
            )
            review = session.scalar(
                select(AgentReview)
                .where(
                    AgentReview.candidate_id == candidate_id,
                    AgentReview.application_id == application_id,
                )
                .order_by(AgentReview.created_at.desc())
                .limit(1)
            )
            reviewed_materials = (
                self._reviewed_materials(session, application, review) if review is not None else ()
            )
            reviewed_documents = tuple(item[0] for item in reviewed_materials)
            rendered_artifacts = tuple(item[1] for item in reviewed_materials)

            answers = session.scalars(
                select(ApplicationAnswer).where(
                    ApplicationAnswer.candidate_id == candidate_id,
                    ApplicationAnswer.application_id == application_id,
                )
            ).all()
            unresolved_actions = session.scalar(
                select(func.count(HumanAction.id)).where(
                    HumanAction.candidate_id == candidate_id,
                    HumanAction.application_id == application_id,
                    HumanAction.status == "pending",
                )
            )
            unresolved_security = session.scalar(
                select(func.count(SecurityEvent.id)).where(
                    SecurityEvent.candidate_id == candidate_id,
                    SecurityEvent.application_id == application_id,
                    SecurityEvent.resolved.is_(False),
                )
            )
            browser_session = session.scalar(
                select(BrowserSession).where(
                    BrowserSession.candidate_id == candidate_id,
                    BrowserSession.application_id == application_id,
                )
            )
            browser_upload_hashes = self._browser_upload_hashes(session, application)
            rendered_cv = next(
                (item for item in rendered_artifacts if item.kind == "rendered_cv"), None
            )
            browser_package_valid = rendered_cv is not None and browser_upload_hashes == (
                rendered_cv.sha256,
            )
            equivalent_application_count = session.scalar(
                select(func.count(Application.id)).where(
                    Application.candidate_id == candidate_id,
                    Application.submission_identity_hash == application.submission_identity_hash,
                    Application.id != application.id,
                )
            )
            duplicate_application = (
                application.submission_identity_hash is None
                or application.submitted_at is not None
                or (equivalent_application_count or 0) > 0
            )
            rate_limits_allowed = job is not None and self._rate_limits_allow(
                session, candidate_id, job.company, settings, now
            )
            gate_input = SubmissionGateInput(
                candidate_id=candidate_id,
                application_id=application_id,
                job_still_open=job is not None
                and self._job_is_fresh(job, now, self._SUBMISSION_FRESHNESS),
                official_or_verified_source=job is not None
                and job.source_trust_level != "unverified",
                duplicate_application=duplicate_application,
                company_not_blocked=job is not None
                and job.company.casefold()
                not in {value.casefold() for value in config.companies.blocked},
                role_not_blocked=job is not None
                and job.title.casefold()
                not in {value.casefold() for value in config.roles.blocked},
                classification_allowed=score is not None and score.meets_threshold,
                mandatory_requirements_compatible=score is not None,
                location_compatible=score is not None
                and "location_incompatible" not in score.rationale.get("hard_blockers", []),
                language_compatible=score is not None
                and not any(
                    str(item).startswith("language_incompatible")
                    for item in score.rationale.get("hard_blockers", [])
                ),
                availability_compatible=config.preferences.full_time_start is not None,
                legal_status_approved=config.manifest.validation.legal_status_approved,
                work_authorization_answer_approved=config.legal_status.approved_for_automated_use,
                salary_policy_compatible=score is not None
                and "salary_below_minimum" not in score.rationale.get("hard_blockers", []),
                candidate_snapshot_valid=config.manifest.validation.profile_approved,
                cv_render_valid=any(item.kind == "rendered_cv" for item in rendered_artifacts),
                cover_letter_valid=not config.cover_letter_rules.enabled
                or any(item.kind == "rendered_cover_letter" for item in rendered_artifacts),
                answers_valid=all(item.supported for item in answers),
                unsupported_claims_count=0 if review and review.semantic_passed else 1,
                unresolved_sensitive_questions_count=sum(
                    1 for item in answers if not item.supported
                ),
                prompt_injection_risk_allowed=job is not None and not job.security_findings,
                captcha_pending=bool(unresolved_actions),
                target_domain_validated=job is not None and job.application_url is not None,
                final_page_matches_job=browser_session is not None
                and browser_session.status == "ready"
                and browser_package_valid,
                pre_submit_archive_created=True,
                rate_limits_allowed=rate_limits_allowed,
                configuration_valid=self._candidates.readiness(candidate_id).status == "ready",
                candidate_score=int(score.total_score) if score else None,
                application_threshold=config.scoring_rules.application_threshold,
                answers_complete=bool(answers),
                answers_supported=all(item.supported for item in answers),
                documents_valid=bool(reviewed_documents)
                and all(item.validated for item in reviewed_documents),
                semantic_review_passed=review.semantic_passed if review else False,
                workflow_state=application.state,
                unresolved_security_events=bool(unresolved_security),
                human_review_required=True,
                human_review_approved=application.state is ApplicationState.READY_TO_SUBMIT,
            )
            gate = SubmissionGate(authorization_ttl=timedelta(minutes=5))
            preflight = gate.evaluate(gate_input)
            if preflight.authorization is None:
                raise ApplicationConflictError(
                    "submission gate denied: " + ", ".join(preflight.reasons)
                )
            if application.archive_uri is None:
                application.archive_uri = str(
                    self._create_archive(session, config, application, job, score, answers)
                )
            snapshot_record = self._reviewed_snapshot(session, application, reviewed_materials)
            archive_ready = self._archive_matches_package(
                application, reviewed_materials, snapshot_record
            )
            decision = gate.evaluate(
                gate_input.model_copy(update={"pre_submit_archive_created": archive_ready})
            )
            if decision.authorization is None:
                raise ApplicationConflictError(
                    "submission gate denied: " + ", ".join(decision.reasons)
                )
            package_sha256 = self._submission_package_sha256(
                application,
                reviewed_materials,
                snapshot_record,
                browser_upload_hashes,
            )
            if existing is not None and _utc(existing.expires_at) > now:
                if existing.package_sha256 != package_sha256:
                    raise ApplicationConflictError(
                        "existing authorization does not match the current submission package"
                    )
                view = self._authorization_view(existing)
                self._append_administrative_command_receipt(
                    session,
                    candidate_id,
                    "authorize_application",
                    key_sha256,
                    request_sha256,
                    view.model_dump(mode="json"),
                )
                return view
            authorization = decision.authorization
            record = SubmissionAuthorizationRecord(
                authorization_id=authorization.authorization_id,
                candidate_id=candidate_id,
                application_id=application_id,
                workflow_state=authorization.workflow_state,
                issued_at=authorization.issued_at,
                expires_at=authorization.expires_at,
                package_sha256=package_sha256,
            )
            session.add(record)
            session.add(
                ApplicationEvent(
                    candidate_id=candidate_id,
                    application_id=application_id,
                    idempotency_key=idempotency_key,
                    event_type="SUBMISSION_AUTHORIZED",
                    from_state=application.state,
                    to_state=application.state,
                    payload={"authorization_id": str(record.authorization_id)},
                )
            )
            session.flush()
            view = self._authorization_view(record)
            self._append_administrative_command_receipt(
                session,
                candidate_id,
                "authorize_application",
                key_sha256,
                request_sha256,
                view.model_dump(mode="json"),
            )
            return view

    def submit_synthetic(
        self,
        candidate_id: str,
        application_id: UUID,
        request: SyntheticSubmissionRequest,
        idempotency_key: str,
    ) -> SubmissionResultView:
        with self._candidates.lifecycle_write(candidate_id):
            return self._submit_synthetic(candidate_id, application_id, request, idempotency_key)

    def _submit_synthetic(
        self,
        candidate_id: str,
        application_id: UUID,
        request: SyntheticSubmissionRequest,
        idempotency_key: str,
    ) -> SubmissionResultView:
        with self._sessions() as lookup:
            application = self._application(lookup, candidate_id, application_id)
            replay = lookup.scalar(
                select(ApplicationEvent).where(
                    ApplicationEvent.candidate_id == candidate_id,
                    ApplicationEvent.application_id == application_id,
                    ApplicationEvent.idempotency_key.in_(
                        (f"{idempotency_key}:confirmed", f"{idempotency_key}:unconfirmed")
                    ),
                )
            )
            if replay is not None:
                if replay.payload.get("authorization_id") != str(request.authorization_id):
                    raise ApplicationConflictError(
                        "idempotency key was reused with another request"
                    )
                successful = replay.event_type == "SUBMISSION_CONFIRMED"
                return SubmissionResultView(
                    application_id=application_id,
                    state=replay.to_state,
                    successful=successful,
                    status="confirmed" if successful else "confirmation_missing",
                    confirmation_reference=(
                        str(replay.payload["confirmation_reference"])
                        if replay.payload.get("confirmation_reference") is not None
                        else None
                    ),
                )
            record = lookup.get(SubmissionAuthorizationRecord, request.authorization_id)
            if (
                record is None
                or record.candidate_id != candidate_id
                or record.application_id != application_id
            ):
                raise ApplicationConflictError("submission authorization was not found")
            issued_at = _utc(record.issued_at)
            expires_at = _utc(record.expires_at)
            job_id = application.job_id
        # Reconstructing a gate object is intentionally impossible. Consumption of API-issued
        # records is performed transactionally below and is still state/expiry bound.
        now = datetime.now(UTC)
        if now < issued_at or now >= expires_at:
            raise ApplicationConflictError("submission authorization is expired")
        self._revalidate_job(job_id)
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            application = self._application(session, candidate_id, application_id)
            record = session.get(SubmissionAuthorizationRecord, request.authorization_id)
            if (
                record is None
                or record.candidate_id != candidate_id
                or record.application_id != application_id
            ):
                raise ApplicationConflictError("submission authorization was not found")
            if record.consumed_at is not None:
                raise ApplicationConflictError("submission authorization was already consumed")
            if application.state is not ApplicationState.READY_TO_SUBMIT:
                raise ApplicationConflictError("application is no longer ready to submit")
            job = session.get(GlobalJob, application.job_id)
            if job is None or not self._job_is_fresh(job, now, self._SUBMISSION_FRESHNESS):
                raise ApplicationConflictError(
                    "job source could not confirm the opening immediately before submission"
                )
            if application.submission_identity_hash is None:
                raise ApplicationConflictError("application duplicate identity is missing")
            duplicate_application = session.scalar(
                select(func.count(Application.id)).where(
                    Application.candidate_id == candidate_id,
                    Application.submission_identity_hash == application.submission_identity_hash,
                    Application.id != application.id,
                )
            )
            if duplicate_application:
                raise ApplicationConflictError("candidate has an equivalent application")
            review = session.scalar(
                select(AgentReview)
                .where(
                    AgentReview.candidate_id == candidate_id,
                    AgentReview.application_id == application_id,
                )
                .order_by(AgentReview.created_at.desc())
                .limit(1)
            )
            if review is None:
                raise ApplicationConflictError("material review is missing")
            reviewed_materials = self._reviewed_materials(session, application, review)
            snapshot_record = self._reviewed_snapshot(session, application, reviewed_materials)
            browser_upload_hashes = self._browser_upload_hashes(session, application)
            rendered_cv = next(
                artifact
                for _document, artifact in reviewed_materials
                if artifact.kind == "rendered_cv"
            )
            if browser_upload_hashes != (rendered_cv.sha256,):
                raise ApplicationConflictError(
                    "browser upload does not match the reviewed rendered CV"
                )
            package_sha256 = self._submission_package_sha256(
                application,
                reviewed_materials,
                snapshot_record,
                browser_upload_hashes,
            )
            if record.package_sha256 is None or not hmac.compare_digest(
                record.package_sha256, package_sha256
            ):
                raise ApplicationConflictError(
                    "submission authorization does not match the current package"
                )
            claimed = session.execute(
                update(SubmissionAuthorizationRecord)
                .where(
                    SubmissionAuthorizationRecord.authorization_id == request.authorization_id,
                    SubmissionAuthorizationRecord.candidate_id == candidate_id,
                    SubmissionAuthorizationRecord.application_id == application_id,
                    SubmissionAuthorizationRecord.consumed_at.is_(None),
                )
                .values(consumed_at=now)
                .returning(SubmissionAuthorizationRecord.authorization_id)
            ).scalar_one_or_none()
            if claimed is None:
                raise ApplicationConflictError("submission authorization was already consumed")
            settings = self._settings_record(session, candidate_id)
            if settings.emergency_stopped:
                raise ApplicationConflictError("emergency stop is active")
            if not self._rate_limits_allow(session, candidate_id, job.company, settings, now):
                raise ApplicationConflictError("candidate application rate limit is active")
            self._transition(
                session,
                application,
                ApplicationState.SUBMITTING,
                f"{idempotency_key}:submitting",
                "SYNTHETIC_SUBMISSION_STARTED",
                payload={"live_click": False},
            )
            self._transition(
                session,
                application,
                ApplicationState.SUBMITTED,
                f"{idempotency_key}:submitted",
                "SYNTHETIC_APPLICATION_SUBMITTED",
                payload={"live_click": False},
            )
            confirmation_reference = self._synthetic_confirmation(candidate_id, application_id)
            backend_confirmation_detected = confirmation_reference is not None
            browser_session = session.scalar(
                select(BrowserSession).where(
                    BrowserSession.candidate_id == candidate_id,
                    BrowserSession.application_id == application_id,
                )
            )
            if backend_confirmation_detected:
                assert confirmation_reference is not None
                application.confirmation_reference = confirmation_reference
                application.submitted_at = now
                application.outcome = ApplicationOutcome.SUBMITTED
                if browser_session is not None:
                    browser_session.status = "confirmed"
                self._transition(
                    session,
                    application,
                    ApplicationState.CONFIRMED,
                    f"{idempotency_key}:confirmed",
                    "SUBMISSION_CONFIRMED",
                    payload={
                        "confirmation_reference": confirmation_reference,
                        "authorization_id": str(request.authorization_id),
                    },
                )
                session.flush()
                if application.archive_uri is None:
                    raise ApplicationConflictError("pre-submit archive is missing")
                events = session.scalars(
                    select(ApplicationEvent)
                    .where(
                        ApplicationEvent.candidate_id == candidate_id,
                        ApplicationEvent.application_id == application_id,
                    )
                    .order_by(ApplicationEvent.occurred_at, ApplicationEvent.id)
                ).all()
                pre_submit_archive = Path(application.archive_uri)
                confirmed_archive = self._archives.finalize_confirmed(
                    pre_submit_archive,
                    confirmation_reference=confirmation_reference,
                    submitted_at=now,
                    event_log=[
                        {
                            "event_type": item.event_type,
                            "occurred_at": item.occurred_at,
                            "payload": item.payload,
                        }
                        for item in events
                    ],
                )
                application.archive_uri = str(confirmed_archive)
                confirmed_files = {
                    "manifest.json": ("archive_manifest", 2, "application/json"),
                    "submission/receipt.json": (
                        "submission_receipt",
                        2,
                        "application/json",
                    ),
                    "submission/confirmation_screenshot.png": (
                        "confirmation_screenshot",
                        1,
                        "image/png",
                    ),
                    "submission/confirmation.html": (
                        "submission_confirmation",
                        1,
                        "text/html",
                    ),
                }
                for relative_path, (kind, version, content_type) in confirmed_files.items():
                    path = confirmed_archive / relative_path
                    session.add(
                        ApplicationArtifact(
                            candidate_id=candidate_id,
                            application_id=application_id,
                            kind=kind,
                            version=version,
                            storage_uri=str(path),
                            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            content_type=content_type,
                            immutable=True,
                            artifact_metadata={
                                "archive_uri": str(confirmed_archive),
                                "pre_submit_archive_uri": str(pre_submit_archive),
                                "relative_path": relative_path,
                                "backend_confirmed": True,
                            },
                        )
                    )
                status = "confirmed"
            else:
                self._transition(
                    session,
                    application,
                    ApplicationState.FAILED_RETRYABLE,
                    f"{idempotency_key}:unconfirmed",
                    "SUBMISSION_CONFIRMATION_MISSING",
                    payload={"authorization_id": str(request.authorization_id)},
                )
                status = "confirmation_missing"
        return SubmissionResultView(
            application_id=application_id,
            state=application.state,
            successful=backend_confirmation_detected,
            status=status,
            confirmation_reference=application.confirmation_reference,
        )

    def withdraw(
        self, candidate_id: str, application_id: UUID, idempotency_key: str
    ) -> ApplicationDetail:
        with self._candidates.lifecycle_write(candidate_id), self._sessions.begin() as session:
            payload = {"application_id": str(application_id)}
            replay, request_sha256, key_sha256 = self._administrative_command_replay(
                session, candidate_id, "withdraw_application", payload, idempotency_key
            )
            if replay is not None:
                return ApplicationDetail.model_validate(replay)
            application = self._application(session, candidate_id, application_id)
            self._transition(
                session,
                application,
                ApplicationState.WITHDRAWN,
                idempotency_key,
                "APPLICATION_WITHDRAWN",
            )
            application.outcome = ApplicationOutcome.WITHDRAWN
            session.flush()
            view = self._detail(session, application)
            self._append_administrative_command_receipt(
                session,
                candidate_id,
                "withdraw_application",
                key_sha256,
                request_sha256,
                view.model_dump(mode="json"),
            )
            return view

    def list_artifacts(self, candidate_id: str, application_id: UUID) -> tuple[ArtifactView, ...]:
        with self._sessions() as session:
            self._application(session, candidate_id, application_id)
            artifacts = session.scalars(
                select(ApplicationArtifact).where(
                    ApplicationArtifact.candidate_id == candidate_id,
                    ApplicationArtifact.application_id == application_id,
                )
            ).all()
            return tuple(self._artifact_view(item) for item in artifacts)

    def list_correspondence(
        self, candidate_id: str, application_id: UUID | None = None
    ) -> tuple[CorrespondenceView, ...]:
        self._candidates.get_config(candidate_id)
        with self._sessions() as session:
            query = select(StoredCorrespondence).where(
                StoredCorrespondence.candidate_id == candidate_id
            )
            if application_id is not None:
                self._application(session, candidate_id, application_id)
                query = query.where(StoredCorrespondence.application_id == application_id)
            records = session.scalars(query.order_by(StoredCorrespondence.received_at.desc())).all()
            return tuple(self._correspondence_view(item) for item in records)

    def ingest_correspondence(
        self, request: CorrespondenceIngestRequest, idempotency_key: str
    ) -> CorrespondenceView:
        with (
            self._candidates.lifecycle_write(request.candidate_id) as config,
            self._sessions.begin() as session,
        ):
            payload = request.model_dump(mode="json")
            replay, request_sha256, key_sha256 = self._administrative_command_replay(
                session,
                request.candidate_id,
                "ingest_correspondence",
                payload,
                idempotency_key,
            )
            if replay is not None:
                return CorrespondenceView.model_validate(replay)
            existing = session.scalar(
                select(StoredCorrespondence).where(
                    StoredCorrespondence.candidate_id == request.candidate_id,
                    StoredCorrespondence.external_message_id == request.provider_message_id,
                )
            )
            applications = session.scalars(
                select(Application).where(Application.candidate_id == request.candidate_id)
            ).all()
            references: list[ApplicationReference] = []
            for application in applications:
                job = session.get(GlobalJob, application.job_id)
                if job is None:
                    continue
                references.append(
                    ApplicationReference(
                        candidate_id=request.candidate_id,
                        application_id=application.id,
                        company=job.company,
                        company_domain=job.company_domain or "unknown.invalid",
                        job_title=job.title,
                        external_references=(job.external_id,),
                    )
                )
            classified = self._correspondence.ingest(
                candidate_id=request.candidate_id,
                message=MessageFixture(
                    provider_message_id=request.provider_message_id,
                    thread_id=request.thread_id,
                    sender=request.sender,
                    recipients=request.recipients,
                    subject=request.subject,
                    body_text=request.body_text,
                    received_at=request.received_at,
                ),
                applications=references,
            )
            if existing is not None:
                if not hmac.compare_digest(existing.body_sha256, classified.message_sha256):
                    raise ApplicationConflictError(
                        "provider message ID was reused with changed correspondence"
                    )
                view = self._correspondence_view(existing)
                self._append_administrative_command_receipt(
                    session,
                    request.candidate_id,
                    "ingest_correspondence",
                    key_sha256,
                    request_sha256,
                    view.model_dump(mode="json"),
                )
                return view
            record = StoredCorrespondence(
                candidate_id=request.candidate_id,
                application_id=classified.application_id,
                external_message_id=request.provider_message_id,
                kind=classified.kind.value,
                sender=request.sender,
                subject=request.subject,
                received_at=request.received_at,
                body_sha256=classified.message_sha256,
                metadata_payload={
                    "association_reason": classified.association_reason,
                    "thread_id": request.thread_id,
                },
            )
            session.add(record)
            session.flush()
            if classified.application_id is not None:
                application = self._application(
                    session, request.candidate_id, classified.application_id
                )
                targets = {
                    CorrespondenceKind.REJECTION: ApplicationState.REJECTED,
                    CorrespondenceKind.INTERVIEW: ApplicationState.INTERVIEW,
                    CorrespondenceKind.OFFER: ApplicationState.OFFER,
                }
                target = targets.get(classified.kind)
                if target is not None and target in VALID_TRANSITIONS[application.state]:
                    self._transition(
                        session,
                        application,
                        target,
                        idempotency_key,
                        f"CORRESPONDENCE_{classified.kind.value.upper()}",
                        payload={"correspondence_id": str(record.id)},
                    )
            event_type = f"correspondence_{classified.kind.value}"
            notification_rules = config.notification_rules
            if (
                classified.kind is not CorrespondenceKind.UNKNOWN
                and config.manifest.workflow.notifications_enabled
                and notification_rules.approved
                and "web" in notification_rules.channels
            ):
                session.add(
                    NotificationRecord(
                        candidate_id=request.candidate_id,
                        application_id=classified.application_id,
                        event_type=event_type,
                        channel="dashboard",
                        message=request.subject,
                        immediate=event_type in notification_rules.immediate_events,
                    )
                )
            view = self._correspondence_view(record)
            self._append_administrative_command_receipt(
                session,
                request.candidate_id,
                "ingest_correspondence",
                key_sha256,
                request_sha256,
                view.model_dump(mode="json"),
            )
            return view

    def prepare_interview(
        self, candidate_id: str, application_id: UUID, idempotency_key: str
    ) -> InterviewPreparationPackage:
        with self._candidates.lifecycle_write(candidate_id):
            return self._prepare_interview(candidate_id, application_id, idempotency_key)

    def _prepare_interview(
        self, candidate_id: str, application_id: UUID, idempotency_key: str
    ) -> InterviewPreparationPackage:
        with self._sessions.begin() as session:
            payload = {"application_id": str(application_id)}
            replay, request_sha256, key_sha256 = self._administrative_command_replay(
                session,
                candidate_id,
                "prepare_interview",
                payload,
                idempotency_key,
            )
            if replay is not None:
                return InterviewPreparationPackage.model_validate(replay)
            application = self._application(session, candidate_id, application_id)
            existing = session.scalar(
                select(ApplicationArtifact).where(
                    ApplicationArtifact.candidate_id == candidate_id,
                    ApplicationArtifact.application_id == application_id,
                    ApplicationArtifact.kind == "interview_package",
                    ApplicationArtifact.version == 1,
                )
            )
            if existing is not None:
                package = InterviewPreparationPackage.model_validate_json(
                    Path(existing.storage_uri).read_text(encoding="utf-8")
                )
                self._append_administrative_command_receipt(
                    session,
                    candidate_id,
                    "prepare_interview",
                    key_sha256,
                    request_sha256,
                    package.model_dump(mode="json"),
                )
                return package
            job = session.get(GlobalJob, application.job_id)
            score = (
                session.get(CandidateJobScore, application.score_id)
                if application.score_id
                else None
            )
            if job is None or score is None:
                raise ApplicationConflictError("job evidence is missing for interview preparation")
            documents = session.scalars(
                select(ApplicationDocument).where(
                    ApplicationDocument.candidate_id == candidate_id,
                    ApplicationDocument.application_id == application_id,
                )
            ).all()
            answers = session.scalars(
                select(ApplicationAnswer).where(
                    ApplicationAnswer.candidate_id == candidate_id,
                    ApplicationAnswer.application_id == application_id,
                )
            ).all()
            correspondence = session.scalars(
                select(StoredCorrespondence).where(
                    StoredCorrespondence.candidate_id == candidate_id,
                    StoredCorrespondence.application_id == application_id,
                )
            ).all()
            by_kind = {item.kind.value: item for item in documents}
            cv = by_kind.get(DocumentKind.CV.value)
            if cv is None or not self._source_document_valid(cv):
                raise ApplicationConflictError("exact CV is missing for interview preparation")
            cover_letter = by_kind.get(DocumentKind.COVER_LETTER.value)
            if cover_letter is not None and not self._source_document_valid(cover_letter):
                raise ApplicationConflictError(
                    "exact cover letter is missing for interview preparation"
                )
            evidence = tuple(str(item) for item in score.rationale.get("evidence", []))
            package = self._correspondence.prepare_interview(
                ArchivedApplicationArtifacts(
                    candidate_id=candidate_id,
                    application_id=application_id,
                    company=job.company,
                    job_title=job.title,
                    exact_cv=Path(cv.storage_uri).read_text(encoding="utf-8"),
                    exact_cover_letter=(
                        Path(cover_letter.storage_uri).read_text(encoding="utf-8")
                        if cover_letter
                        else None
                    ),
                    submitted_answers=tuple(
                        SubmittedAnswer(question=item.question, answer=item.answer)
                        for item in answers
                    ),
                    original_job_description=job.description,
                    job_score=int(score.total_score),
                    score_rationale=json.dumps(score.rationale, sort_keys=True),
                    candidate_job_match_summary=(
                        f"Candidate-scoped score {int(score.total_score)} for {job.title}."
                    ),
                    required_skills=tuple(job.required_skills),
                    relevant_projects=tuple(
                        item.removeprefix("project:")
                        for item in evidence
                        if item.startswith("project:")
                    ),
                    unsupported_areas=tuple(score.rationale.get("hard_blockers", [])),
                    recruiter_correspondence=tuple(item.subject for item in correspondence),
                )
            )
            content = canonical_json_bytes(package.model_dump(mode="json"))
            path = self._write_exclusive(
                candidate_id,
                application_id,
                "interview_package",
                "interview-package-v1.json",
                content,
            )
            session.add(
                ApplicationArtifact(
                    candidate_id=candidate_id,
                    application_id=application_id,
                    kind="interview_package",
                    version=1,
                    storage_uri=str(path),
                    sha256=hashlib.sha256(content).hexdigest(),
                    content_type="application/json",
                    immutable=True,
                    artifact_metadata={"source_artifacts_sha256": package.source_artifacts_sha256},
                )
            )
            self._append_administrative_command_receipt(
                session,
                candidate_id,
                "prepare_interview",
                key_sha256,
                request_sha256,
                package.model_dump(mode="json"),
            )
            return package

    def list_notifications(self, candidate_id: str) -> tuple[NotificationView, ...]:
        self._candidates.get_config(candidate_id)
        with self._sessions() as session:
            records = session.scalars(
                select(NotificationRecord)
                .where(NotificationRecord.candidate_id == candidate_id)
                .order_by(NotificationRecord.created_at.desc())
            ).all()
            return tuple(self._notification_view(item) for item in records)

    def artifact_path(self, candidate_id: str, application_id: UUID, artifact_id: UUID) -> Path:
        with self._candidates.lifecycle_read(candidate_id):
            return self._artifact_path(candidate_id, application_id, artifact_id)

    def _artifact_path(self, candidate_id: str, application_id: UUID, artifact_id: UUID) -> Path:
        with self._sessions() as session:
            artifact = session.scalar(
                select(ApplicationArtifact).where(
                    ApplicationArtifact.id == artifact_id,
                    ApplicationArtifact.candidate_id == candidate_id,
                    ApplicationArtifact.application_id == application_id,
                )
            )
            if artifact is None:
                raise ApplicationNotFoundError("artifact not found")
            path = Path(artifact.storage_uri).resolve()
            if not path.is_relative_to(self._runtime_root) or not path.is_file():
                raise ApplicationConflictError("artifact storage reference is invalid")
            if hashlib.sha256(path.read_bytes()).hexdigest() != artifact.sha256:
                raise ApplicationConflictError("artifact hash verification failed")
            return path

    def artifact_chunks(
        self,
        candidate_id: str,
        application_id: UUID,
        artifact_id: UUID,
        *,
        chunk_size: int = 64 * 1024,
    ) -> Iterator[bytes]:
        """Stream an artifact while holding the candidate lifecycle reader lease."""
        with self._candidates.lifecycle_read(candidate_id):
            path = self._artifact_path(candidate_id, application_id, artifact_id)
            with path.open("rb") as artifact:
                while chunk := artifact.read(chunk_size):
                    yield chunk

    def list_human_actions(self, candidate_id: str) -> tuple[HumanActionView, ...]:
        self._candidates.get_config(candidate_id)
        with self._sessions() as session:
            actions = session.scalars(
                select(HumanAction)
                .where(HumanAction.candidate_id == candidate_id)
                .order_by(HumanAction.occurred_at.desc())
            ).all()
            return tuple(self._human_action_view(session, item) for item in actions)

    def open_human_session(
        self, candidate_id: str, action_id: UUID, idempotency_key: str
    ) -> HumanActionView:
        with self._candidates.lifecycle_write(candidate_id):
            return self._open_human_session(candidate_id, action_id, idempotency_key)

    def _open_human_session(
        self, candidate_id: str, action_id: UUID, idempotency_key: str
    ) -> HumanActionView:
        with self._sessions.begin() as session:
            payload = {"action_id": str(action_id)}
            replay, request_sha256, key_sha256 = self._administrative_command_replay(
                session, candidate_id, "open_human_session", payload, idempotency_key
            )
            if replay is not None:
                return HumanActionView.model_validate(replay)
            action = session.scalar(
                select(HumanAction).where(
                    HumanAction.id == action_id,
                    HumanAction.candidate_id == candidate_id,
                )
            )
            if action is None:
                raise ApplicationNotFoundError("human action not found")
            if action.status != "pending":
                raise ApplicationConflictError("human action is no longer pending")
            if action.expires_at is not None and _utc(action.expires_at) <= datetime.now(UTC):
                raise ApplicationConflictError("human action has expired")
            if action.browser_session_id is None:
                raise ApplicationConflictError("human action has no browser session")
            browser_session = session.get(BrowserSession, action.browser_session_id)
            if (
                browser_session is None
                or browser_session.candidate_id != candidate_id
                or browser_session.application_id != action.application_id
            ):
                raise ApplicationConflictError("candidate browser session is unavailable")
            if browser_session.status == "human_takeover_opened":
                view = self._human_action_view(session, action)
                self._append_administrative_command_receipt(
                    session,
                    candidate_id,
                    "open_human_session",
                    key_sha256,
                    request_sha256,
                    view.model_dump(mode="json"),
                )
                return view
            if browser_session.status != "human_action_required":
                raise ApplicationConflictError("browser session is not paused for human action")
            session_reference = Path(browser_session.external_session_ref or "").resolve()
            expected_reference = (
                self._runtime_root
                / "candidates"
                / candidate_id
                / "sessions"
                / str(browser_session.id)
            ).resolve()
            if session_reference != expected_reference or not session_reference.is_dir():
                raise ApplicationConflictError("browser session reference is invalid")
            application = self._application(session, candidate_id, action.application_id)
            if application.state is not ApplicationState.HUMAN_ACTION_REQUIRED:
                raise ApplicationConflictError("application is not awaiting human action")
            browser_session.status = "human_takeover_opened"
            session.add(
                ApplicationEvent(
                    candidate_id=candidate_id,
                    application_id=application.id,
                    idempotency_key=idempotency_key,
                    event_type="HUMAN_SESSION_OPENED",
                    from_state=application.state,
                    to_state=application.state,
                    payload={
                        "action_id": str(action.id),
                        "browser_session_id": str(browser_session.id),
                    },
                )
            )
            session.flush()
            view = self._human_action_view(session, action)
            self._append_administrative_command_receipt(
                session,
                candidate_id,
                "open_human_session",
                key_sha256,
                request_sha256,
                view.model_dump(mode="json"),
            )
            return view

    def complete_human_action(
        self, candidate_id: str, action_id: UUID, idempotency_key: str, *, cancel: bool = False
    ) -> HumanActionView:
        with self._candidates.lifecycle_write(candidate_id):
            return self._complete_human_action(
                candidate_id, action_id, idempotency_key, cancel=cancel
            )

    def _complete_human_action(
        self, candidate_id: str, action_id: UUID, idempotency_key: str, *, cancel: bool = False
    ) -> HumanActionView:
        with self._sessions.begin() as session:
            payload = {"action_id": str(action_id), "cancel": cancel}
            operation = "cancel_human_action" if cancel else "complete_human_action"
            replay, request_sha256, key_sha256 = self._administrative_command_replay(
                session, candidate_id, operation, payload, idempotency_key
            )
            if replay is not None:
                return HumanActionView.model_validate(replay)
            action = session.scalar(
                select(HumanAction).where(
                    HumanAction.id == action_id,
                    HumanAction.candidate_id == candidate_id,
                )
            )
            if action is None:
                raise ApplicationNotFoundError("human action not found")
            if action.status != "pending":
                expected_status = "cancelled" if cancel else "completed"
                if action.status != expected_status:
                    raise ApplicationConflictError(
                        f"human action is already {action.status}; cannot mark it {expected_status}"
                    )
                view = self._human_action_view(session, action)
                self._append_administrative_command_receipt(
                    session,
                    candidate_id,
                    operation,
                    key_sha256,
                    request_sha256,
                    view.model_dump(mode="json"),
                )
                return view
            if action.expires_at is not None and _utc(action.expires_at) <= datetime.now(UTC):
                raise ApplicationConflictError("human action has expired")
            application = self._application(session, candidate_id, action.application_id)
            if application.state is not ApplicationState.HUMAN_ACTION_REQUIRED:
                raise ApplicationConflictError("application is not awaiting human action")
            if not cancel and action.browser_session_id is not None:
                browser_session = session.get(BrowserSession, action.browser_session_id)
                if (
                    browser_session is None
                    or browser_session.candidate_id != candidate_id
                    or browser_session.application_id != action.application_id
                    or browser_session.status != "human_takeover_opened"
                ):
                    raise ApplicationConflictError(
                        "open the recoverable browser session before completing the action"
                    )
                session_reference = Path(browser_session.external_session_ref or "").resolve()
                expected_reference = (
                    self._runtime_root
                    / "candidates"
                    / candidate_id
                    / "sessions"
                    / str(browser_session.id)
                ).resolve()
                if session_reference != expected_reference or not session_reference.is_dir():
                    raise ApplicationConflictError("browser session reference is invalid")
                if not self._human_action_session_verifier(
                    candidate_id,
                    action.application_id,
                    browser_session.id,
                    session_reference,
                ):
                    raise ApplicationConflictError(
                        "browser session has not verified human-action completion"
                    )
                browser_session.status = "ready"
            elif cancel and action.browser_session_id is not None:
                browser_session = session.get(BrowserSession, action.browser_session_id)
                if browser_session is not None and browser_session.candidate_id == candidate_id:
                    browser_session.status = "cancelled"
            action.status = "cancelled" if cancel else "completed"
            action.completed_at = datetime.now(UTC)
            target = ApplicationState.WITHDRAWN if cancel else ApplicationState.FINAL_VALIDATION
            self._transition(
                session,
                application,
                target,
                idempotency_key,
                "HUMAN_ACTION_CANCELLED" if cancel else "HUMAN_ACTION_COMPLETED",
            )
            if not cancel:
                self._transition(
                    session,
                    application,
                    ApplicationState.READY_TO_SUBMIT,
                    f"{idempotency_key}:ready",
                    "FINAL_VALIDATION_PASSED",
                )
            session.flush()
            view = self._human_action_view(session, action)
            self._append_administrative_command_receipt(
                session,
                candidate_id,
                operation,
                key_sha256,
                request_sha256,
                view.model_dump(mode="json"),
            )
            return view

    def list_security_events(self, candidate_id: str) -> tuple[SecurityEventView, ...]:
        self._candidates.get_config(candidate_id)
        with self._sessions() as session:
            events = session.scalars(
                select(SecurityEvent)
                .where(SecurityEvent.candidate_id == candidate_id)
                .order_by(SecurityEvent.occurred_at.desc())
            ).all()
            return tuple(self._security_view(item) for item in events)

    def resolve_security_event(
        self, candidate_id: str, event_id: UUID, idempotency_key: str
    ) -> SecurityEventView:
        with self._candidates.lifecycle_write(candidate_id), self._sessions.begin() as session:
            replay, request_sha256, key_sha256 = self._administrative_command_replay(
                session,
                candidate_id,
                "resolve_security_event",
                {"event_id": str(event_id)},
                idempotency_key,
            )
            if replay is not None:
                return SecurityEventView.model_validate(replay)
            event = session.scalar(
                select(SecurityEvent).where(
                    SecurityEvent.id == event_id,
                    SecurityEvent.candidate_id == candidate_id,
                )
            )
            if event is None:
                raise ApplicationNotFoundError("security event not found")
            if not event.resolved:
                event.resolved = True
                self._append_admin_audit(
                    session,
                    candidate_id,
                    "security_event_resolved",
                    {"security_event_id": str(event_id)},
                )
            view = self._security_view(event)
            self._append_administrative_command_receipt(
                session,
                candidate_id,
                "resolve_security_event",
                key_sha256,
                request_sha256,
                view.model_dump(mode="json"),
            )
            return view

    def get_settings(self, candidate_id: str) -> SettingsView:
        config = self._candidates.get_config(candidate_id)
        with self._sessions() as session:
            record = session.scalar(
                select(CandidateSettingsRecord).where(
                    CandidateSettingsRecord.candidate_id == candidate_id
                )
            ) or self._default_settings_record(candidate_id)
            return self._settings_view(config, record)

    def update_settings(self, update: SettingsUpdate, idempotency_key: str) -> SettingsView:
        with self._candidates.lifecycle_write(update.candidate_id):
            return self._update_settings(update, idempotency_key)

    def _update_settings(self, update: SettingsUpdate, idempotency_key: str) -> SettingsView:
        config = self._candidates.get_config(update.candidate_id)
        with self._sessions.begin() as session:
            payload = update.model_dump(mode="json", exclude_none=True)
            replay, request_sha256, key_sha256 = self._settings_command_replay(
                session,
                update.candidate_id,
                "settings_updated",
                payload,
                idempotency_key,
            )
            if replay is not None:
                return replay
            record = self._settings_record(session, update.candidate_id)
            values = update.model_dump(exclude_none=True, exclude={"candidate_id"})
            for key, value in values.items():
                setattr(record, key, list(value) if isinstance(value, tuple) else value)
            view = self._settings_view(config, record)
            if view.automation_mode == "autonomous" and view.autonomy_blockers:
                raise ApplicationConflictError(
                    "autonomous mode is blocked: " + ", ".join(view.autonomy_blockers)
                )
            self._append_admin_audit(
                session,
                update.candidate_id,
                "settings_updated",
                {"fields": sorted(values), "automation_mode": view.automation_mode},
            )
            self._append_settings_receipt(
                session,
                update.candidate_id,
                "settings_updated",
                key_sha256,
                request_sha256,
                view,
            )
            return view

    def emergency_stop(self, candidate_id: str, idempotency_key: str) -> SettingsView:
        with self._candidates.lifecycle_write(candidate_id):
            return self._emergency_stop(candidate_id, idempotency_key)

    def _emergency_stop(self, candidate_id: str, idempotency_key: str) -> SettingsView:
        config = self._candidates.get_config(candidate_id)
        with self._sessions.begin() as session:
            replay, request_sha256, key_sha256 = self._settings_command_replay(
                session,
                candidate_id,
                "emergency_stop_activated",
                {"candidate_id": candidate_id},
                idempotency_key,
            )
            if replay is not None:
                return replay
            record = self._settings_record(session, candidate_id)
            record.emergency_stopped = True
            record.automation_mode = "disabled"
            self._append_admin_audit(
                session, candidate_id, "emergency_stop_activated", {"automation_mode": "disabled"}
            )
            view = self._settings_view(config, record)
            self._append_settings_receipt(
                session,
                candidate_id,
                "emergency_stop_activated",
                key_sha256,
                request_sha256,
                view,
            )
            return view

    def analytics(self, candidate_id: str) -> AnalyticsOverview:
        self._candidates.get_config(candidate_id)
        with self._sessions() as session:
            applications = session.scalars(
                select(Application).where(Application.candidate_id == candidate_id)
            ).all()
            scores = [
                session.get(CandidateJobScore, item.score_id)
                for item in applications
                if item.score_id is not None
            ]
            role_categories = Counter(
                str(score.rationale.get("classification", "unknown"))
                for score in scores
                if score is not None
            )
            return AnalyticsOverview(
                candidate_id=candidate_id,
                applications=len(applications),
                average_score=(
                    round(
                        sum(float(score.total_score) for score in scores if score is not None)
                        / len(scores),
                        2,
                    )
                    if scores
                    else 0.0
                ),
                by_state=dict(Counter(item.state.value for item in applications)),
                by_role_category=dict(role_categories),
                human_actions_pending=session.scalar(
                    select(func.count(HumanAction.id)).where(
                        HumanAction.candidate_id == candidate_id,
                        HumanAction.status == "pending",
                    )
                )
                or 0,
                security_events_unresolved=session.scalar(
                    select(func.count(SecurityEvent.id)).where(
                        SecurityEvent.candidate_id == candidate_id,
                        SecurityEvent.resolved.is_(False),
                    )
                )
                or 0,
                confirmations=sum(
                    item.state is ApplicationState.CONFIRMED for item in applications
                ),
            )

    def _generation_request(
        self, config: CandidateConfig, application_id: UUID, job: GlobalJob
    ) -> GenerationRequest:
        facts: list[ApprovedFact] = []
        if config.biography.approved:
            facts.append(
                ApprovedFact(
                    fact_id="biography_summary",
                    text=config.biography.summary,
                    source_path="biography.summary",
                )
            )
        for experience in config.experience.items:
            if (
                not experience.approved
                or experience.archived
                or experience.confidentiality != "public"
            ):
                continue
            document_kinds = tuple(
                kind
                for kind, eligible in (
                    (DocumentKind.CV, experience.cv_eligible),
                    (DocumentKind.COVER_LETTER, experience.cover_letter_eligible),
                )
                if eligible
            )
            for index, achievement in enumerate(experience.achievements):
                if not isinstance(achievement, ClaimFact):
                    continue
                if (
                    not achievement.approved
                    or achievement.archived
                    or not achievement.verified
                    or not achievement.publicly_usable
                    or achievement.confidentiality != "public"
                ):
                    continue
                facts.append(
                    ApprovedFact(
                        fact_id=achievement.id,
                        text=achievement.statement,
                        source_path=f"experience.{experience.id}.achievements[{index}]",
                        document_kinds=document_kinds,
                    )
                )
        for project in config.projects.items:
            if not project.approved or project.archived or project.confidentiality == "internal":
                continue
            description = (
                project.description
                if project.confidentiality == "public"
                else project.public_summary
            )
            if not description:
                continue
            document_kinds = tuple(
                kind
                for kind, eligible in (
                    (DocumentKind.CV, project.cv_eligible),
                    (DocumentKind.COVER_LETTER, project.cover_letter_eligible),
                )
                if eligible
            )
            facts.append(
                ApprovedFact(
                    fact_id=f"{project.id}_description",
                    text=description,
                    source_path=(
                        f"projects.{project.id}.description"
                        if project.confidentiality == "public"
                        else f"projects.{project.id}.public_summary"
                    ),
                    document_kinds=document_kinds,
                )
            )
            for index, outcome in enumerate(project.outcomes):
                if not isinstance(outcome, ClaimFact):
                    continue
                if (
                    not outcome.approved
                    or outcome.archived
                    or not outcome.verified
                    or not outcome.publicly_usable
                    or outcome.confidentiality != "public"
                ):
                    continue
                facts.append(
                    ApprovedFact(
                        fact_id=outcome.id,
                        text=outcome.statement,
                        source_path=f"projects.{project.id}.outcomes[{index}]",
                        document_kinds=document_kinds,
                    )
                )
        today = date.today()
        usable_answers = tuple(
            item
            for item in config.approved_answers.items
            if item.approved
            and item.auto_submit_allowed
            and not item.archived
            and (item.valid_from is None or item.valid_from <= today)
            and (item.valid_until is None or item.valid_until >= today)
        )
        answers = tuple(
            ApprovedAnswerFact(
                key=item.key,
                question_pattern=item.question_pattern,
                answer=item.answer,
                evidence_ids=item.evidence_ids,
            )
            for item in usable_answers
        )
        requested_documents = [DocumentKind.CV]
        if config.cover_letter_rules.enabled:
            requested_documents.append(DocumentKind.COVER_LETTER)
        return GenerationRequest(
            candidate_id=config.manifest.candidate_id,
            application_id=application_id,
            target=JobTarget(company=job.company, title=job.title),
            requested_documents=tuple(requested_documents),
            approved_facts=tuple(facts),
            approved_answers=answers,
            answer_prompts=tuple(
                AnswerPrompt(question_key=item.key, question=item.question_pattern)
                for item in config.approved_answers.items
                if not item.archived
            ),
        )

    def _write_exclusive(
        self,
        candidate_id: str,
        application_id: UUID,
        kind: str,
        filename: str,
        content: bytes,
    ) -> Path:
        if not kind or not kind.replace("_", "").isalnum() or Path(filename).name != filename:
            raise ApplicationConflictError("artifact path contains an unsafe segment")
        application_root = self._candidate_application_root(
            candidate_id, application_id, create=True
        )
        directory = application_root / kind
        if directory.is_symlink():
            raise ApplicationConflictError("artifact directory contains a symlink")
        directory.mkdir(parents=True, exist_ok=True)
        if directory.resolve() != directory:
            raise ApplicationConflictError("artifact directory is unsafe")
        path = directory / filename
        if path.is_symlink():
            raise ApplicationConflictError("artifact path contains a symlink")
        try:
            with path.open("xb") as output:
                output.write(content)
        except FileExistsError:
            if path.read_bytes() != content:
                raise ApplicationConflictError(
                    "immutable artifact version already exists"
                ) from None
        return path

    def _candidate_application_root(
        self, candidate_id: str, application_id: UUID, *, create: bool
    ) -> Path:
        if not candidate_id or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in candidate_id
        ):
            raise ApplicationConflictError("candidate artifact scope is invalid")
        candidates_root = self._runtime_root / "candidates"
        candidate_root = candidates_root / candidate_id
        archive_root = candidate_root / "application_archive"
        application_root = archive_root / str(application_id)
        if create:
            self._runtime_root.mkdir(parents=True, exist_ok=True)
        if not self._runtime_root.is_dir():
            raise ApplicationConflictError("runtime artifact root is unavailable")
        components = (
            (candidates_root, self._runtime_root),
            (candidate_root, candidates_root),
            (archive_root, candidate_root),
            (application_root, archive_root),
        )
        for path, expected_parent in components:
            if path.is_symlink():
                raise ApplicationConflictError("candidate artifact path contains a symlink")
            if create and not path.exists():
                path.mkdir()
            if path.exists() and (
                not path.is_dir() or path.resolve() != path or path.parent != expected_parent
            ):
                raise ApplicationConflictError("candidate artifact path is unsafe")
        return application_root

    def _render_artifact_valid(
        self,
        artifact: ApplicationArtifact,
        *,
        document: ApplicationDocument,
        snapshot: CandidateSnapshotRecord,
    ) -> bool:
        if (
            artifact.content_type != "application/pdf"
            or artifact.artifact_metadata.get("valid") is not True
            or artifact.artifact_metadata.get("pdf_sha256") != artifact.sha256
            or artifact.artifact_metadata.get("source_sha256") != document.sha256
            or artifact.artifact_metadata.get("document_version") != document.version
            or artifact.artifact_metadata.get("candidate_snapshot_version")
            != snapshot.profile_version
            or artifact.artifact_metadata.get("candidate_snapshot_sha256") != snapshot.sha256
            or artifact.candidate_id != document.candidate_id
            or artifact.application_id != document.application_id
            or artifact.version != document.version
            or artifact.kind != f"rendered_{document.kind.value}"
        ):
            return False
        try:
            application_root = self._candidate_application_root(
                artifact.candidate_id, artifact.application_id, create=False
            )
        except ApplicationConflictError:
            return False
        path = Path(artifact.storage_uri).absolute()
        expected = application_root / artifact.kind / f"v{artifact.version}.pdf"
        if path != expected or path.is_symlink() or path.parent.is_symlink() or not path.is_file():
            return False
        return hashlib.sha256(path.read_bytes()).hexdigest() == artifact.sha256

    def _source_document_valid(self, document: ApplicationDocument) -> bool:
        try:
            application_root = self._candidate_application_root(
                document.candidate_id, document.application_id, create=False
            )
        except ApplicationConflictError:
            return False
        path = Path(document.storage_uri).absolute()
        expected = application_root / document.kind.value / f"v{document.version}.txt"
        if path != expected or path.is_symlink() or path.parent.is_symlink() or not path.is_file():
            return False
        return hashlib.sha256(path.read_bytes()).hexdigest() == document.sha256

    def _load_candidate_snapshot(
        self, application: Application, record: CandidateSnapshotRecord
    ) -> CandidateSnapshot:
        try:
            application_root = self._candidate_application_root(
                application.candidate_id, application.id, create=False
            )
        except ApplicationConflictError as exc:
            raise ApplicationConflictError(
                "candidate snapshot storage reference is invalid"
            ) from exc
        path = Path(record.storage_uri).absolute()
        expected = application_root / "candidate_snapshot" / f"{record.sha256}.json"
        if path != expected or path.is_symlink() or path.parent.is_symlink():
            raise ApplicationConflictError("candidate snapshot storage reference is invalid")
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ApplicationConflictError(
                "candidate snapshot storage reference is invalid"
            ) from exc
        if resolved != expected or not resolved.is_file():
            raise ApplicationConflictError("candidate snapshot storage reference is invalid")
        try:
            snapshot = CandidateSnapshot.model_validate_json(resolved.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ApplicationConflictError("candidate snapshot validation failed") from exc
        if (
            snapshot.candidate_id != application.candidate_id
            or snapshot.profile_version != record.profile_version
            or snapshot.config_sha256 != record.sha256
            or hashlib.sha256(snapshot.config_json.encode("utf-8")).hexdigest() != record.sha256
        ):
            raise ApplicationConflictError("candidate snapshot identity mismatch")
        return snapshot

    def _reviewed_materials(
        self, session: Session, application: Application, review: AgentReview
    ) -> tuple[tuple[ApplicationDocument, ApplicationArtifact], ...]:
        try:
            material_review = MaterialReview.model_validate(review.report)
        except ValueError as exc:
            raise ApplicationConflictError("material review record is invalid") from exc
        if not review.semantic_passed or not material_review.semantic_review_passed:
            raise ApplicationConflictError("materials did not pass independent review")
        if not material_review.render_reports:
            raise ApplicationConflictError("material review has no rendered document identity")
        reviewed: list[tuple[ApplicationDocument, ApplicationArtifact]] = []
        seen_kinds: set[DocumentKind] = set()
        snapshot_ids: set[UUID] = set()
        for report in material_review.render_reports:
            if not report.valid or report.pdf_sha256 is None or report.document_kind in seen_kinds:
                raise ApplicationConflictError("material review contains invalid render identity")
            seen_kinds.add(report.document_kind)
            document = session.scalar(
                select(ApplicationDocument).where(
                    ApplicationDocument.candidate_id == application.candidate_id,
                    ApplicationDocument.application_id == application.id,
                    ApplicationDocument.kind == report.document_kind,
                    ApplicationDocument.version == report.document_version,
                )
            )
            artifact = session.scalar(
                select(ApplicationArtifact).where(
                    ApplicationArtifact.candidate_id == application.candidate_id,
                    ApplicationArtifact.application_id == application.id,
                    ApplicationArtifact.kind == f"rendered_{report.document_kind.value}",
                    ApplicationArtifact.version == report.document_version,
                    ApplicationArtifact.sha256 == report.pdf_sha256,
                )
            )
            if (
                document is None
                or artifact is None
                or not document.validated
                or not self._source_document_valid(document)
            ):
                raise ApplicationConflictError(
                    f"reviewed {report.document_kind.value.upper()} source is missing or corrupted"
                )
            snapshot_id = artifact.artifact_metadata.get("candidate_snapshot_id")
            try:
                snapshot_uuid = UUID(str(snapshot_id))
            except ValueError as exc:
                raise ApplicationConflictError(
                    "rendered document snapshot identity is invalid"
                ) from exc
            snapshot = session.get(CandidateSnapshotRecord, snapshot_uuid)
            snapshot_ids.add(snapshot_uuid)
            if (
                snapshot is None
                or snapshot.candidate_id != application.candidate_id
                or snapshot.application_id != application.id
                or artifact.artifact_metadata.get("template_id") != report.template_id
                or artifact.artifact_metadata.get("template_version") != report.template_version
                or artifact.artifact_metadata.get("source_sha256") != report.source_sha256
            ):
                raise ApplicationConflictError("reviewed rendered document identity mismatch")
            if not self._render_artifact_valid(artifact, document=document, snapshot=snapshot):
                raise ApplicationConflictError(
                    f"rendered {report.document_kind.value.upper()} is missing or corrupted"
                )
            reviewed.append((document, artifact))
        if DocumentKind.CV not in seen_kinds:
            raise ApplicationConflictError("reviewed rendered CV is missing")
        if len(snapshot_ids) != 1:
            raise ApplicationConflictError("reviewed documents use different candidate snapshots")
        return tuple(reviewed)

    @staticmethod
    def _browser_upload_hashes(session: Session, application: Application) -> tuple[str, ...]:
        event = session.scalar(
            select(ApplicationEvent)
            .where(
                ApplicationEvent.candidate_id == application.candidate_id,
                ApplicationEvent.application_id == application.id,
                ApplicationEvent.event_type == "FINAL_VALIDATION_STARTED",
            )
            .order_by(ApplicationEvent.occurred_at.desc())
            .limit(1)
        )
        if event is None:
            return ()
        final_page = event.payload.get("final_page")
        values = final_page.get("upload_hashes") if isinstance(final_page, dict) else None
        if not isinstance(values, list) or not all(
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
            for value in values
        ):
            return ()
        return tuple(values)

    @staticmethod
    def _reviewed_snapshot(
        session: Session,
        application: Application,
        materials: tuple[tuple[ApplicationDocument, ApplicationArtifact], ...],
    ) -> CandidateSnapshotRecord:
        snapshot_id = UUID(str(materials[0][1].artifact_metadata["candidate_snapshot_id"]))
        snapshot = session.get(CandidateSnapshotRecord, snapshot_id)
        if (
            snapshot is None
            or snapshot.candidate_id != application.candidate_id
            or snapshot.application_id != application.id
        ):
            raise ApplicationConflictError("reviewed candidate snapshot is missing")
        return snapshot

    def _archive_matches_package(
        self,
        application: Application,
        materials: tuple[tuple[ApplicationDocument, ApplicationArtifact], ...],
        snapshot: CandidateSnapshotRecord,
    ) -> bool:
        if application.archive_uri is None:
            return False
        path = self._safe_archive_path(application.archive_uri)
        if path is None or not self._archives.verify(path):
            return False
        try:
            manifest = ArchiveManifest.model_validate_json(
                (path / "manifest.json").read_text(encoding="utf-8")
            )
            archived_snapshot = CandidateSnapshot.model_validate_json(
                (path / "candidate_snapshot" / "profile.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return False
        artifacts = {artifact.kind: artifact for _document, artifact in materials}
        expected_cover = artifacts.get("rendered_cover_letter")
        return (
            manifest.candidate_id == application.candidate_id
            and manifest.application_id == application.id
            and manifest.status == "ready_to_submit"
            and archived_snapshot.snapshot_id == snapshot.id
            and archived_snapshot.config_sha256 == snapshot.sha256
            and manifest.cv.get("sha256") == artifacts["rendered_cv"].sha256
            and manifest.cover_letter.get("sha256")
            == (expected_cover.sha256 if expected_cover is not None else None)
        )

    def _submission_package_sha256(
        self,
        application: Application,
        materials: tuple[tuple[ApplicationDocument, ApplicationArtifact], ...],
        snapshot: CandidateSnapshotRecord,
        browser_upload_hashes: tuple[str, ...],
    ) -> str:
        if not self._archive_matches_package(application, materials, snapshot):
            raise ApplicationConflictError("pre-submit archive does not match reviewed package")
        assert application.archive_uri is not None
        archive_path = self._safe_archive_path(application.archive_uri)
        if archive_path is None:
            raise ApplicationConflictError("pre-submit archive path is unsafe")
        manifest_path = archive_path / "manifest.json"
        package = {
            "candidate_id": application.candidate_id,
            "application_id": str(application.id),
            "workflow_state": application.state.value,
            "candidate_snapshot_id": str(snapshot.id),
            "candidate_snapshot_sha256": snapshot.sha256,
            "documents": [
                {
                    "kind": artifact.kind,
                    "version": artifact.version,
                    "source_sha256": document.sha256,
                    "pdf_sha256": artifact.sha256,
                }
                for document, artifact in sorted(materials, key=lambda item: item[1].kind)
            ],
            "browser_upload_hashes": sorted(browser_upload_hashes),
            "archive_manifest_sha256": sha256_bytes(manifest_path.read_bytes()),
        }
        return sha256_bytes(canonical_json_bytes(package))

    def _safe_archive_path(self, archive_uri: str) -> Path | None:
        archive_root = (self._runtime_root / "application_archive").resolve()
        raw_path = Path(archive_uri).absolute()
        if raw_path.is_symlink():
            return None
        try:
            path = raw_path.resolve(strict=True)
        except OSError:
            return None
        if not path.is_relative_to(archive_root):
            return None
        for parent in (raw_path, *raw_path.parents):
            if parent == archive_root:
                break
            if parent.is_symlink():
                return None
        return path

    def _create_archive(
        self,
        session: Session,
        config: CandidateConfig,
        application: Application,
        job: GlobalJob | None,
        score: CandidateJobScore | None,
        answers: Sequence[ApplicationAnswer],
    ) -> Path:
        events = session.scalars(
            select(ApplicationEvent).where(
                ApplicationEvent.candidate_id == application.candidate_id,
                ApplicationEvent.application_id == application.id,
            )
        ).all()
        security_events = session.scalars(
            select(SecurityEvent).where(
                SecurityEvent.candidate_id == application.candidate_id,
                SecurityEvent.application_id == application.id,
            )
        ).all()
        review = session.scalar(
            select(AgentReview)
            .where(
                AgentReview.candidate_id == application.candidate_id,
                AgentReview.application_id == application.id,
            )
            .order_by(AgentReview.created_at.desc())
            .limit(1)
        )
        if review is None:
            raise ApplicationConflictError("material review is missing")
        reviewed_materials = self._reviewed_materials(session, application, review)
        reviewed_documents = tuple(item[0] for item in reviewed_materials)
        rendered_artifacts = tuple(item[1] for item in reviewed_materials)
        snapshot_id = UUID(str(rendered_artifacts[0].artifact_metadata["candidate_snapshot_id"]))
        snapshot_record = session.get(CandidateSnapshotRecord, snapshot_id)
        if snapshot_record is None:
            raise ApplicationConflictError("candidate snapshot is missing")
        candidate_snapshot = self._load_candidate_snapshot(application, snapshot_record)

        archive = self._archives.create(
            candidate_id=application.candidate_id,
            application_id=application.id,
            recover_existing=True,
            data=ApplicationArchiveData(
                candidate_snapshot=candidate_snapshot.model_dump(mode="json"),
                job_snapshot={
                    "id": str(job.id) if job else None,
                    "external_id": job.external_id if job else None,
                    "company": job.company if job else None,
                    "company_domain": job.company_domain if job else None,
                    "title": job.title if job else None,
                    "source_url": job.url if job else None,
                    "application_url": job.application_url if job else None,
                    "description_raw": job.description if job else None,
                    "description_normalized": job.description_normalized if job else None,
                },
                scoring_results={
                    **(score.rationale if score else {}),
                    "total_score": float(score.total_score) if score else None,
                },
                generated_document_references=[
                    {
                        "kind": item.kind.removeprefix("rendered_"),
                        "version": item.version,
                        "sha256": item.sha256,
                        "storage_uri": item.storage_uri,
                        "content_type": item.content_type,
                        "template_id": item.artifact_metadata.get("template_id"),
                        "template_version": item.artifact_metadata.get("template_version"),
                    }
                    for item in rendered_artifacts
                ],
                answers=[
                    {
                        "question": item.question,
                        "question_key": item.question_key,
                        "answer": item.answer,
                        "supported": item.supported,
                    }
                    for item in answers
                ],
                validation_report={
                    "documents_valid": all(item.validated for item in reviewed_documents),
                    "render_reports": [item.artifact_metadata for item in rendered_artifacts],
                },
                event_log=[
                    {
                        "event_type": item.event_type,
                        "occurred_at": item.occurred_at,
                        "payload": item.payload,
                    }
                    for item in events
                ],
                security_event_log=[
                    {
                        "category": item.category,
                        "severity": item.severity,
                        "details": item.details,
                        "resolved": item.resolved,
                        "occurred_at": item.occurred_at,
                    }
                    for item in security_events
                ],
                error_log=[
                    {
                        "event_type": item.event_type,
                        "occurred_at": item.occurred_at,
                        "payload": item.payload,
                    }
                    for item in events
                    if "FAILED" in item.event_type or "ERROR" in item.event_type
                ],
                required_document_kinds=(
                    ("cv", "cover_letter") if config.cover_letter_rules.enabled else ("cv",)
                ),
            ),
        )
        exposed_files = {
            "manifest.json": ("archive_manifest", "application/json"),
            "candidate_snapshot/profile.json": ("candidate_snapshot", "application/json"),
            "scoring/validation_report.json": ("validation_report", "application/json"),
            "submitted_documents/cv_submitted.pdf": ("submitted_cv", "application/pdf"),
            "submitted_documents/cover_letter_submitted.pdf": (
                "submitted_cover_letter",
                "application/pdf",
            ),
            "answers/final_answers.json": ("submitted_answers", "application/json"),
            "submission/pre_submit_screenshot.png": ("pre_submit_screenshot", "image/png"),
            "submission/final_page_snapshot.html": ("final_page_snapshot", "text/html"),
            "submission/receipt.json": ("submission_receipt", "application/json"),
            "audit/events.jsonl": ("application_audit", "application/x-ndjson"),
        }
        for relative_path, (kind, content_type) in exposed_files.items():
            path = archive / relative_path
            if not path.is_file():
                continue
            session.add(
                ApplicationArtifact(
                    candidate_id=application.candidate_id,
                    application_id=application.id,
                    kind=kind,
                    version=1,
                    storage_uri=str(path),
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    content_type=content_type,
                    immutable=True,
                    artifact_metadata={
                        "archive_uri": str(archive),
                        "relative_path": relative_path,
                        "submitted_exact": kind.startswith("submitted_"),
                    },
                )
            )
        return archive

    def _transition(
        self,
        session: Session,
        application: Application,
        target: ApplicationState,
        idempotency_key: str,
        event_type: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> None:
        existing = session.scalar(
            select(ApplicationEvent).where(
                ApplicationEvent.candidate_id == application.candidate_id,
                ApplicationEvent.application_id == application.id,
                ApplicationEvent.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.to_state is not target:
                raise ApplicationConflictError("idempotency key was reused for another transition")
            return
        if target not in VALID_TRANSITIONS[application.state]:
            raise ApplicationConflictError(
                f"invalid application transition: {application.state.value} -> {target.value}"
            )
        previous = application.state
        application.state = target
        application.state_version += 1
        session.add(
            ApplicationEvent(
                candidate_id=application.candidate_id,
                application_id=application.id,
                idempotency_key=idempotency_key,
                event_type=event_type,
                from_state=previous,
                to_state=target,
                payload=payload or {},
            )
        )
        session.flush()

    def _revalidate_job(self, job_id: UUID) -> VerificationEvidence:
        """Persist source evidence independently from a later fail-closed mutation."""

        with self._sessions.begin() as session:
            job = session.get(GlobalJob, job_id)
            if job is None:
                raise ApplicationNotFoundError(f"job not found: {job_id}")
            evidence = self._source_verifier.verify(job)
            apply_verification(job, evidence)
            session.flush()
            return evidence

    @staticmethod
    def _job_is_fresh(job: GlobalJob, now: datetime, maximum_age: timedelta) -> bool:
        checked_at = job.verification_checked_at
        if checked_at is None or job.verification_status != "open":
            return False
        checked_at = _utc(checked_at)
        return (
            checked_at <= now
            and now - checked_at <= maximum_age
            and job.verified_open_at is not None
            and job.verification_evidence_sha256 is not None
            and len(job.verification_evidence_sha256) == 64
        )

    @staticmethod
    def _application(session: Session, candidate_id: str, application_id: UUID) -> Application:
        application = session.scalar(
            select(Application).where(
                Application.id == application_id,
                Application.candidate_id == candidate_id,
            )
        )
        if application is None:
            raise ApplicationNotFoundError(f"application not found: {application_id}")
        return application

    def _summary(self, session: Session, application: Application) -> ApplicationSummary:
        job = session.get(GlobalJob, application.job_id)
        score = (
            session.get(CandidateJobScore, application.score_id) if application.score_id else None
        )
        last_event = session.scalar(
            select(ApplicationEvent.event_type)
            .where(
                ApplicationEvent.candidate_id == application.candidate_id,
                ApplicationEvent.application_id == application.id,
            )
            .order_by(ApplicationEvent.occurred_at.desc())
            .limit(1)
        )
        return ApplicationSummary(
            application_id=application.id,
            candidate_id=application.candidate_id,
            job_id=application.job_id,
            company=job.company if job else "Unknown company",
            role=job.title if job else "Unknown role",
            score=int(score.total_score) if score else None,
            state=application.state,
            last_event=last_event,
            updated_at=application.updated_at,
            next_action=self._next_action(application.state),
        )

    def _detail(self, session: Session, application: Application) -> ApplicationDetail:
        summary = self._summary(session, application)
        job = session.get(GlobalJob, application.job_id)
        documents = session.scalars(
            select(ApplicationDocument)
            .where(
                ApplicationDocument.candidate_id == application.candidate_id,
                ApplicationDocument.application_id == application.id,
            )
            .order_by(ApplicationDocument.kind, ApplicationDocument.version)
        ).all()
        answers = session.scalars(
            select(ApplicationAnswer).where(
                ApplicationAnswer.candidate_id == application.candidate_id,
                ApplicationAnswer.application_id == application.id,
            )
        ).all()
        events = session.scalars(
            select(ApplicationEvent)
            .where(
                ApplicationEvent.candidate_id == application.candidate_id,
                ApplicationEvent.application_id == application.id,
            )
            .order_by(ApplicationEvent.occurred_at)
        ).all()
        review = session.scalar(
            select(AgentReview)
            .where(
                AgentReview.candidate_id == application.candidate_id,
                AgentReview.application_id == application.id,
            )
            .order_by(AgentReview.created_at.desc())
            .limit(1)
        )
        correspondence = session.scalars(
            select(StoredCorrespondence)
            .where(
                StoredCorrespondence.candidate_id == application.candidate_id,
                StoredCorrespondence.application_id == application.id,
            )
            .order_by(StoredCorrespondence.received_at)
        ).all()
        immutable_kinds = {
            item.kind
            for item in session.scalars(
                select(ApplicationArtifact).where(
                    ApplicationArtifact.candidate_id == application.candidate_id,
                    ApplicationArtifact.application_id == application.id,
                    ApplicationArtifact.immutable.is_(True),
                )
            ).all()
        }
        if any(not self._source_document_valid(item) for item in documents):
            raise ApplicationConflictError("application source document is missing or corrupted")
        return ApplicationDetail(
            **summary.model_dump(),
            source_url=job.url if job else "",
            ats_platform=job.ats_platform if job else None,
            documents=tuple(
                DocumentView(
                    document_id=item.id,
                    kind=item.kind.value,
                    version=item.version,
                    content=Path(item.storage_uri).read_text(encoding="utf-8"),
                    sha256=item.sha256,
                    immutable=item.kind.value in immutable_kinds,
                    validated=item.validated,
                    evidence_ids=tuple(item.evidence_ids.get("items", [])),
                    created_at=item.created_at,
                )
                for item in documents
            ),
            answers=tuple(
                AnswerView(
                    answer_id=item.id,
                    question_key=item.question_key,
                    question=item.question,
                    answer=item.answer,
                    supported=item.supported,
                    evidence_ids=tuple(item.evidence_ids.get("items", [])),
                )
                for item in answers
            ),
            events=tuple(
                EventView(
                    event_id=item.id,
                    event_type=item.event_type,
                    from_state=item.from_state,
                    to_state=item.to_state,
                    occurred_at=item.occurred_at,
                    payload=item.payload,
                )
                for item in events
            ),
            review=(
                ReviewView(
                    decision=review.decision,
                    semantic_passed=review.semantic_passed,
                    report=review.report,
                )
                if review
                else None
            ),
            correspondence=tuple(self._correspondence_view(item) for item in correspondence),
            archive_available=application.archive_uri is not None,
            confirmation_reference=application.confirmation_reference,
            submitted_at=application.submitted_at,
        )

    @staticmethod
    def _next_action(state: ApplicationState) -> str:
        return {
            ApplicationState.REVIEW_PENDING: "Approve materials",
            ApplicationState.APPLICATION_STARTED: "Start synthetic dry run",
            ApplicationState.FORM_FILLING: "Complete dry run",
            ApplicationState.HUMAN_ACTION_REQUIRED: "Complete human action",
            ApplicationState.READY_TO_SUBMIT: "Authorize synthetic submission",
            ApplicationState.FAILED_RETRYABLE: "Inspect and retry",
        }.get(state, "Inspect details")

    @staticmethod
    def _authorization_view(record: SubmissionAuthorizationRecord) -> AuthorizationView:
        return AuthorizationView(
            authorization_id=record.authorization_id,
            application_id=record.application_id,
            candidate_id=record.candidate_id,
            workflow_state=record.workflow_state,
            issued_at=record.issued_at,
            expires_at=record.expires_at,
        )

    @staticmethod
    def _artifact_view(item: ApplicationArtifact) -> ArtifactView:
        return ArtifactView(
            artifact_id=item.id,
            application_id=item.application_id,
            candidate_id=item.candidate_id,
            kind=item.kind,
            version=item.version,
            sha256=item.sha256,
            content_type=item.content_type,
            immutable=item.immutable,
            download_path=(
                f"/api/applications/{item.application_id}/artifacts/{item.id}"
                f"?candidate_id={item.candidate_id}"
            ),
            metadata=item.artifact_metadata,
            created_at=item.created_at,
        )

    @staticmethod
    def _human_action_view(session: Session, action: HumanAction) -> HumanActionView:
        application = session.get(Application, action.application_id)
        job = session.get(GlobalJob, application.job_id) if application else None
        browser_session = (
            session.get(BrowserSession, action.browser_session_id)
            if action.browser_session_id is not None
            else None
        )
        return HumanActionView(
            action_id=action.id,
            candidate_id=action.candidate_id,
            application_id=action.application_id,
            company=job.company if job else "Unknown company",
            role=job.title if job else "Unknown role",
            kind=action.kind or action.action.value,
            status=action.status,
            reason=action.reason,
            created_at=action.occurred_at,
            expires_at=action.expires_at,
            screenshot_available=action.screenshot_uri is not None,
            browser_session_id=action.browser_session_id,
            session_opened=browser_session is not None
            and browser_session.status == "human_takeover_opened",
        )

    @staticmethod
    def _security_view(event: SecurityEvent) -> SecurityEventView:
        return SecurityEventView(
            event_id=event.id,
            candidate_id=event.candidate_id,
            application_id=event.application_id,
            category=event.category,
            severity=event.severity,
            details=event.details,
            resolved=event.resolved,
            occurred_at=event.occurred_at,
        )

    @staticmethod
    def _correspondence_view(record: StoredCorrespondence) -> CorrespondenceView:
        return CorrespondenceView(
            correspondence_id=record.id,
            candidate_id=record.candidate_id,
            application_id=record.application_id,
            provider_message_id=record.external_message_id,
            kind=record.kind,
            sender=record.sender,
            subject=record.subject,
            received_at=record.received_at,
            association_reason=str(
                record.metadata_payload.get("association_reason", "persisted_association")
            ),
        )

    @staticmethod
    def _notification_view(record: NotificationRecord) -> NotificationView:
        return NotificationView(
            notification_id=record.id,
            candidate_id=record.candidate_id,
            application_id=record.application_id,
            event_type=record.event_type,
            channel=record.channel,
            message=record.message,
            immediate=record.immediate,
            status=record.status,
            created_at=record.created_at,
        )

    @staticmethod
    def _default_settings_record(candidate_id: str) -> CandidateSettingsRecord:
        return CandidateSettingsRecord(
            candidate_id=candidate_id,
            automation_mode="dry_run",
            discovery_enabled=False,
            emergency_stopped=False,
            allowed_ats_adapters=[],
            tested_ats_adapters=[],
            dry_run_acceptance_passed=False,
            explicit_autonomy_confirmation=False,
            maximum_applications_per_day=5,
            maximum_applications_per_week=20,
            maximum_applications_per_company_30_days=3,
            browser_session_retention_days=30,
        )

    @staticmethod
    def _settings_record(session: Session, candidate_id: str) -> CandidateSettingsRecord:
        record = session.scalar(
            select(CandidateSettingsRecord).where(
                CandidateSettingsRecord.candidate_id == candidate_id
            )
        )
        if record is None:
            record = ApplicationService._default_settings_record(candidate_id)
            session.add(record)
            session.flush()
        return record

    @staticmethod
    def _rate_limits_allow(
        session: Session,
        candidate_id: str,
        company: str,
        settings: CandidateSettingsRecord,
        now: datetime,
    ) -> bool:
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        submitted_today = (
            session.scalar(
                select(func.count(Application.id)).where(
                    Application.candidate_id == candidate_id,
                    Application.submitted_at >= day_start,
                )
            )
            or 0
        )
        submitted_week = (
            session.scalar(
                select(func.count(Application.id)).where(
                    Application.candidate_id == candidate_id,
                    Application.submitted_at >= now - timedelta(days=7),
                )
            )
            or 0
        )
        submitted_company = (
            session.scalar(
                select(func.count(Application.id))
                .join(GlobalJob, GlobalJob.id == Application.job_id)
                .where(
                    Application.candidate_id == candidate_id,
                    Application.submitted_at >= now - timedelta(days=30),
                    func.lower(GlobalJob.company) == company.casefold(),
                )
            )
            or 0
        )
        return (
            submitted_today < settings.maximum_applications_per_day
            and submitted_week < settings.maximum_applications_per_week
            and submitted_company < settings.maximum_applications_per_company_30_days
        )

    @staticmethod
    def _settings_command_replay(
        session: Session,
        candidate_id: str,
        operation: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> tuple[SettingsView | None, str, str]:
        replay, request_sha256, key_sha256 = ApplicationService._administrative_command_replay(
            session, candidate_id, operation, payload, idempotency_key
        )
        return (
            SettingsView.model_validate(replay) if replay is not None else None,
            request_sha256,
            key_sha256,
        )

    @staticmethod
    def _administrative_command_replay(
        session: Session,
        candidate_id: str,
        operation: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> tuple[dict[str, Any] | None, str, str]:
        if not 8 <= len(idempotency_key) <= 128:
            raise ApplicationConflictError("idempotency key is invalid")
        key_sha256 = hashlib.sha256(idempotency_key.encode()).hexdigest()
        request_sha256 = hashlib.sha256(
            canonical_json_bytes(
                {
                    "candidate_id": candidate_id,
                    "operation": operation,
                    "payload": payload,
                }
            )
        ).hexdigest()
        receipt = session.scalar(
            select(AdministrativeCommandReceipt).where(
                AdministrativeCommandReceipt.candidate_id == candidate_id,
                AdministrativeCommandReceipt.idempotency_key_sha256 == key_sha256,
            )
        )
        if receipt is None:
            return None, request_sha256, key_sha256
        if receipt.operation != operation or not hmac.compare_digest(
            receipt.request_sha256, request_sha256
        ):
            raise ApplicationConflictError("idempotency key was reused with another request")
        return receipt.result, request_sha256, key_sha256

    @staticmethod
    def _append_settings_receipt(
        session: Session,
        candidate_id: str,
        operation: str,
        key_sha256: str,
        request_sha256: str,
        view: SettingsView,
    ) -> None:
        ApplicationService._append_administrative_command_receipt(
            session,
            candidate_id,
            operation,
            key_sha256,
            request_sha256,
            view.model_dump(mode="json"),
        )

    @staticmethod
    def _append_administrative_command_receipt(
        session: Session,
        candidate_id: str,
        operation: str,
        key_sha256: str,
        request_sha256: str,
        result: dict[str, Any],
    ) -> None:
        session.add(
            AdministrativeCommandReceipt(
                candidate_id=candidate_id,
                operation=operation,
                idempotency_key_sha256=key_sha256,
                request_sha256=request_sha256,
                result=result,
            )
        )

    @staticmethod
    def _append_admin_audit(
        session: Session,
        candidate_id: str,
        event_type: str,
        details: dict[str, object],
    ) -> None:
        previous = session.scalar(
            select(AdministrativeAuditRecord)
            .where(AdministrativeAuditRecord.candidate_id == candidate_id)
            .order_by(AdministrativeAuditRecord.occurred_at.desc())
            .limit(1)
        )
        occurred_at = datetime.now(UTC)
        previous_hash = previous.event_hash if previous else None
        content = canonical_json_bytes(
            {
                "candidate_id": candidate_id,
                "actor_id": "local-user",
                "event_type": event_type,
                "details": details,
                "previous_hash": previous_hash,
                "occurred_at": occurred_at,
            }
        )
        session.add(
            AdministrativeAuditRecord(
                candidate_id=candidate_id,
                actor_id="local-user",
                event_type=event_type,
                details=details,
                previous_hash=previous_hash,
                event_hash=hashlib.sha256(content).hexdigest(),
                occurred_at=occurred_at,
            )
        )

    @staticmethod
    def _settings_view(config: CandidateConfig, record: CandidateSettingsRecord) -> SettingsView:
        blockers: list[str] = []
        if not config.manifest.validation.profile_approved:
            blockers.append("profile_not_approved")
        if not config.manifest.validation.legal_status_approved:
            blockers.append("legal_status_not_approved")
        if not config.manifest.validation.automatic_answers_approved:
            blockers.append("automatic_answers_not_approved")
        if not record.tested_ats_adapters:
            blockers.append("no_tested_ats_adapter")
        if not record.dry_run_acceptance_passed:
            blockers.append("dry_run_acceptance_not_passed")
        if not record.explicit_autonomy_confirmation:
            blockers.append("explicit_confirmation_missing")
        if record.emergency_stopped:
            blockers.append("emergency_stop_active")
        return SettingsView(
            candidate_id=record.candidate_id,
            automation_mode=record.automation_mode,
            discovery_enabled=record.discovery_enabled,
            emergency_stopped=record.emergency_stopped,
            allowed_ats_adapters=tuple(record.allowed_ats_adapters),
            tested_ats_adapters=tuple(record.tested_ats_adapters),
            dry_run_acceptance_passed=record.dry_run_acceptance_passed,
            explicit_autonomy_confirmation=record.explicit_autonomy_confirmation,
            maximum_applications_per_day=record.maximum_applications_per_day,
            maximum_applications_per_week=record.maximum_applications_per_week,
            maximum_applications_per_company_30_days=(
                record.maximum_applications_per_company_30_days
            ),
            browser_session_retention_days=record.browser_session_retention_days,
            autonomy_blockers=tuple(blockers),
        )
