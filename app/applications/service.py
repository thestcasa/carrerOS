from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.applications.contracts import (
    AnalyticsOverview,
    AnswerView,
    ApplicationDetail,
    ApplicationSummary,
    ArtifactView,
    AuthorizationView,
    DocumentView,
    DryRunCommand,
    EventView,
    HumanActionView,
    ReviewView,
    SecurityEventView,
    SettingsUpdate,
    SettingsView,
    SubmissionResultView,
    SyntheticSubmissionRequest,
)
from app.archive import ApplicationArchiveBuilder, ApplicationArchiveData, canonical_json_bytes
from app.browser import DryRunRequest, FieldKind, SyntheticBrowserDryRunner, UploadArtifact
from app.browser.fixtures import standard_application_form
from app.candidates.models import CandidateConfig
from app.candidates.service import CandidateService
from app.domain.enums import (
    ApplicationOutcome,
    ApplicationState,
    DocumentKind,
    HumanActionKind,
)
from app.domain.models import (
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
    SecurityEvent,
    SubmissionAuthorizationRecord,
)
from app.materials import DeterministicMaterialGenerator, IndependentMaterialReviewer
from app.materials.contracts import (
    AnswerPrompt,
    ApprovedAnswerFact,
    ApprovedFact,
    GenerationRequest,
    JobTarget,
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

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        candidate_service: CandidateService,
        runtime_root: Path,
    ) -> None:
        self._sessions = session_factory
        self._candidates = candidate_service
        self._runtime_root = runtime_root.resolve()
        self._generator = DeterministicMaterialGenerator()
        self._reviewer = IndependentMaterialReviewer()
        self._browser = SyntheticBrowserDryRunner(self._runtime_root)
        self._archives = ApplicationArchiveBuilder(self._runtime_root / "application_archive")
        self._consumer = AuthorizationConsumer(session_factory)

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
        config = self._candidates.get_config(candidate_id)
        if not config.manifest.validation.profile_approved:
            raise ApplicationConflictError("candidate profile is not approved")
        with self._sessions.begin() as session:
            job = session.get(GlobalJob, job_id)
            if job is None:
                raise ApplicationNotFoundError(f"job not found: {job_id}")
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
            if application is None:
                application = Application(
                    candidate_id=candidate_id,
                    job_id=job_id,
                    score_id=score.id,
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
            replay = session.scalar(
                select(ApplicationEvent).where(
                    ApplicationEvent.candidate_id == candidate_id,
                    ApplicationEvent.application_id == application.id,
                    ApplicationEvent.idempotency_key == f"{idempotency_key}:review",
                )
            )
            if replay is not None:
                return self._detail(session, application)

            snapshot = self._candidates.snapshot(candidate_id)
            snapshot_path = self._write_exclusive(
                candidate_id,
                application.id,
                "candidate_snapshot",
                f"{snapshot.config_sha256}.json",
                canonical_json_bytes(snapshot.model_dump(mode="json")),
            )
            session.add(
                CandidateSnapshotRecord(
                    candidate_id=candidate_id,
                    application_id=application.id,
                    profile_version=snapshot.profile_version,
                    sha256=snapshot.config_sha256,
                    storage_uri=str(snapshot_path),
                )
            )
            self._transition(
                session,
                application,
                ApplicationState.CANDIDATE_SNAPSHOT_CREATED,
                f"{idempotency_key}:snapshot",
                "CANDIDATE_SNAPSHOT_CREATED",
            )
            self._transition(
                session,
                application,
                ApplicationState.MATERIALS_GENERATING,
                f"{idempotency_key}:generating",
                "MATERIALS_GENERATION_STARTED",
            )
            request = self._generation_request(config, application.id, job)
            generated = self._generator.generate(request)
            review = self._reviewer.review(request, generated)
            for document in generated.documents:
                latest = session.scalar(
                    select(func.max(ApplicationDocument.version)).where(
                        ApplicationDocument.candidate_id == candidate_id,
                        ApplicationDocument.application_id == application.id,
                        ApplicationDocument.kind == document.kind,
                    )
                )
                version = (latest or 0) + 1
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
                        validated=review.documents_supported,
                    )
                )
            for answer in generated.answers:
                session.add(
                    ApplicationAnswer(
                        candidate_id=candidate_id,
                        application_id=application.id,
                        question_key=answer.question_key,
                        question=answer.question,
                        answer=answer.answer,
                        approved_source_key=answer.approved_source_key,
                        evidence_ids={"items": list(answer.evidence_ids)},
                        supported=answer.supported,
                    )
                )
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
                else "INDEPENDENT_REVIEW_FAILED",
                payload=review.model_dump(mode="json"),
            )
        return self.get_application(candidate_id, application.id)

    def approve_materials(
        self, candidate_id: str, application_id: UUID, idempotency_key: str
    ) -> ApplicationDetail:
        with self._sessions.begin() as session:
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
            if review is None or not review.semantic_passed:
                raise ApplicationConflictError("materials did not pass independent review")
            self._transition(
                session,
                application,
                ApplicationState.APPLICATION_STARTED,
                idempotency_key,
                "MATERIALS_APPROVED",
            )
        return self.get_application(candidate_id, application_id)

    def start(
        self, candidate_id: str, application_id: UUID, idempotency_key: str
    ) -> ApplicationDetail:
        with self._sessions.begin() as session:
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
        return self.get_application(candidate_id, application_id)

    def dry_run(
        self,
        candidate_id: str,
        application_id: UUID,
        command: DryRunCommand,
        idempotency_key: str,
    ) -> ApplicationDetail:
        config = self._candidates.get_config(candidate_id)
        with self._sessions.begin() as session:
            application = self._application(session, candidate_id, application_id)
            if application.state is not ApplicationState.FORM_FILLING:
                raise ApplicationConflictError("application is not ready for form filling")
            document = session.scalar(
                select(ApplicationDocument)
                .where(
                    ApplicationDocument.candidate_id == candidate_id,
                    ApplicationDocument.application_id == application_id,
                    ApplicationDocument.kind == DocumentKind.CV,
                )
                .order_by(ApplicationDocument.version.desc())
                .limit(1)
            )
            if document is None:
                raise ApplicationConflictError("validated CV is missing")
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
                            path=Path(document.storage_uri),
                            sha256=document.sha256,
                        ),
                    ),
                    allowed_upload_sha256=frozenset({document.sha256}),
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
        return self.get_application(candidate_id, application_id)

    def authorize(
        self, candidate_id: str, application_id: UUID, idempotency_key: str
    ) -> AuthorizationView:
        config = self._candidates.get_config(candidate_id)
        with self._sessions.begin() as session:
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
            if existing is not None and _utc(existing.expires_at) > now:
                return self._authorization_view(existing)
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
            if application.archive_uri is None:
                application.archive_uri = str(
                    self._create_archive(
                        session, config, application, job, score, documents, answers
                    )
                )
            gate_input = SubmissionGateInput(
                candidate_id=candidate_id,
                application_id=application_id,
                job_still_open=job is not None
                and (job.deadline is None or _utc(job.deadline) > now),
                official_or_verified_source=job is not None
                and job.source_trust_level != "unverified",
                duplicate_application=application.submitted_at is not None,
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
                availability_compatible=True,
                legal_status_approved=config.manifest.validation.legal_status_approved,
                work_authorization_answer_approved=config.legal_status.approved_for_automated_use,
                salary_policy_compatible=score is not None
                and "salary_below_minimum" not in score.rationale.get("hard_blockers", []),
                candidate_snapshot_valid=True,
                cv_render_valid=any(
                    item.kind is DocumentKind.CV and item.validated for item in documents
                ),
                cover_letter_valid=not config.cover_letter_rules.enabled
                or any(
                    item.kind is DocumentKind.COVER_LETTER and item.validated for item in documents
                ),
                answers_valid=all(item.supported for item in answers),
                unsupported_claims_count=0 if review and review.semantic_passed else 1,
                unresolved_sensitive_questions_count=sum(
                    1 for item in answers if not item.supported
                ),
                prompt_injection_risk_allowed=job is not None and not job.security_findings,
                captcha_pending=bool(unresolved_actions),
                target_domain_validated=job is not None and job.application_url is not None,
                final_page_matches_job=browser_session is not None
                and browser_session.status == "ready",
                pre_submit_archive_created=application.archive_uri is not None,
                configuration_valid=True,
                candidate_score=int(score.total_score) if score else None,
                application_threshold=config.scoring_rules.application_threshold,
                answers_complete=True,
                answers_supported=all(item.supported for item in answers),
                documents_valid=bool(documents) and all(item.validated for item in documents),
                semantic_review_passed=review.semantic_passed if review else False,
                workflow_state=application.state,
                unresolved_security_events=bool(unresolved_security),
                human_review_required=True,
                human_review_approved=application.state is ApplicationState.READY_TO_SUBMIT,
            )
            decision = SubmissionGate(authorization_ttl=timedelta(minutes=5)).evaluate(gate_input)
            if decision.authorization is None:
                raise ApplicationConflictError(
                    "submission gate denied: " + ", ".join(decision.reasons)
                )
            authorization = decision.authorization
            record = SubmissionAuthorizationRecord(
                authorization_id=authorization.authorization_id,
                candidate_id=candidate_id,
                application_id=application_id,
                workflow_state=authorization.workflow_state,
                issued_at=authorization.issued_at,
                expires_at=authorization.expires_at,
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
            return self._authorization_view(record)

    def submit_synthetic(
        self,
        candidate_id: str,
        application_id: UUID,
        request: SyntheticSubmissionRequest,
        idempotency_key: str,
    ) -> SubmissionResultView:
        with self._sessions() as lookup:
            record = lookup.get(SubmissionAuthorizationRecord, request.authorization_id)
            if (
                record is None
                or record.candidate_id != candidate_id
                or record.application_id != application_id
            ):
                raise ApplicationConflictError("submission authorization was not found")
            issued_at = _utc(record.issued_at)
            expires_at = _utc(record.expires_at)
        # Reconstructing a gate object is intentionally impossible. Consumption of API-issued
        # records is performed transactionally below and is still state/expiry bound.
        now = datetime.now(UTC)
        if now < issued_at or now >= expires_at:
            raise ApplicationConflictError("submission authorization is expired")
        with self._sessions.begin() as session:
            application = self._application(session, candidate_id, application_id)
            live_record = session.get(SubmissionAuthorizationRecord, request.authorization_id)
            if live_record is None or live_record.consumed_at is not None:
                raise ApplicationConflictError("submission authorization was already consumed")
            if application.state is not ApplicationState.READY_TO_SUBMIT:
                raise ApplicationConflictError("application is no longer ready to submit")
            settings = self._settings_record(session, candidate_id)
            if settings.emergency_stopped:
                raise ApplicationConflictError("emergency stop is active")
            live_record.consumed_at = now
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
            if request.backend_confirmation_detected:
                application.confirmation_reference = request.confirmation_reference
                application.submitted_at = now
                application.outcome = ApplicationOutcome.SUBMITTED
                self._transition(
                    session,
                    application,
                    ApplicationState.CONFIRMED,
                    f"{idempotency_key}:confirmed",
                    "SUBMISSION_CONFIRMED",
                    payload={"confirmation_reference": request.confirmation_reference},
                )
                status = "confirmed"
            else:
                self._transition(
                    session,
                    application,
                    ApplicationState.FAILED_RETRYABLE,
                    f"{idempotency_key}:unconfirmed",
                    "SUBMISSION_CONFIRMATION_MISSING",
                )
                status = "confirmation_missing"
        return SubmissionResultView(
            application_id=application_id,
            state=application.state,
            successful=request.backend_confirmation_detected,
            status=status,
            confirmation_reference=application.confirmation_reference,
        )

    def withdraw(
        self, candidate_id: str, application_id: UUID, idempotency_key: str
    ) -> ApplicationDetail:
        with self._sessions.begin() as session:
            application = self._application(session, candidate_id, application_id)
            self._transition(
                session,
                application,
                ApplicationState.WITHDRAWN,
                idempotency_key,
                "APPLICATION_WITHDRAWN",
            )
            application.outcome = ApplicationOutcome.WITHDRAWN
        return self.get_application(candidate_id, application_id)

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

    def artifact_path(self, candidate_id: str, application_id: UUID, artifact_id: UUID) -> Path:
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

    def list_human_actions(self, candidate_id: str) -> tuple[HumanActionView, ...]:
        self._candidates.get_config(candidate_id)
        with self._sessions() as session:
            actions = session.scalars(
                select(HumanAction)
                .where(HumanAction.candidate_id == candidate_id)
                .order_by(HumanAction.occurred_at.desc())
            ).all()
            return tuple(self._human_action_view(session, item) for item in actions)

    def complete_human_action(
        self, candidate_id: str, action_id: UUID, idempotency_key: str, *, cancel: bool = False
    ) -> HumanActionView:
        with self._sessions.begin() as session:
            action = session.scalar(
                select(HumanAction).where(
                    HumanAction.id == action_id,
                    HumanAction.candidate_id == candidate_id,
                )
            )
            if action is None:
                raise ApplicationNotFoundError("human action not found")
            if action.status != "pending":
                return self._human_action_view(session, action)
            action.status = "cancelled" if cancel else "completed"
            action.completed_at = datetime.now(UTC)
            application = self._application(session, candidate_id, action.application_id)
            if not cancel and action.browser_session_id is not None:
                browser_session = session.get(BrowserSession, action.browser_session_id)
                if browser_session is not None and browser_session.candidate_id == candidate_id:
                    browser_session.status = "ready"
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
            return self._human_action_view(session, action)

    def list_security_events(self, candidate_id: str) -> tuple[SecurityEventView, ...]:
        self._candidates.get_config(candidate_id)
        with self._sessions() as session:
            events = session.scalars(
                select(SecurityEvent)
                .where(SecurityEvent.candidate_id == candidate_id)
                .order_by(SecurityEvent.occurred_at.desc())
            ).all()
            return tuple(self._security_view(item) for item in events)

    def resolve_security_event(self, candidate_id: str, event_id: UUID) -> SecurityEventView:
        with self._sessions.begin() as session:
            event = session.scalar(
                select(SecurityEvent).where(
                    SecurityEvent.id == event_id,
                    SecurityEvent.candidate_id == candidate_id,
                )
            )
            if event is None:
                raise ApplicationNotFoundError("security event not found")
            event.resolved = True
            return self._security_view(event)

    def get_settings(self, candidate_id: str) -> SettingsView:
        config = self._candidates.get_config(candidate_id)
        with self._sessions.begin() as session:
            record = self._settings_record(session, candidate_id)
            return self._settings_view(config, record)

    def update_settings(self, update: SettingsUpdate) -> SettingsView:
        config = self._candidates.get_config(update.candidate_id)
        with self._sessions.begin() as session:
            record = self._settings_record(session, update.candidate_id)
            values = update.model_dump(exclude_none=True, exclude={"candidate_id"})
            for key, value in values.items():
                setattr(record, key, list(value) if isinstance(value, tuple) else value)
            view = self._settings_view(config, record)
            if view.automation_mode == "autonomous" and view.autonomy_blockers:
                raise ApplicationConflictError(
                    "autonomous mode is blocked: " + ", ".join(view.autonomy_blockers)
                )
            return view

    def emergency_stop(self, candidate_id: str) -> SettingsView:
        config = self._candidates.get_config(candidate_id)
        with self._sessions.begin() as session:
            record = self._settings_record(session, candidate_id)
            record.emergency_stopped = True
            record.automation_mode = "disabled"
            return self._settings_view(config, record)

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
        facts: list[ApprovedFact] = [
            ApprovedFact(
                fact_id="biography_summary",
                text=config.biography.summary,
                source_path="biography.summary",
            )
        ]
        for experience in config.experience.items:
            for index, achievement in enumerate(experience.achievements):
                facts.append(
                    ApprovedFact(
                        fact_id=f"{experience.id}_achievement_{index}",
                        text=achievement,
                        source_path=f"experience.{experience.id}.achievements[{index}]",
                    )
                )
        for project in config.projects.items:
            facts.append(
                ApprovedFact(
                    fact_id=f"{project.id}_description",
                    text=project.description,
                    source_path=f"projects.{project.id}.description",
                )
            )
        answers = tuple(
            ApprovedAnswerFact(
                key=item.key,
                question_pattern=item.question_pattern,
                answer=item.answer,
                evidence_ids=item.evidence_ids,
            )
            for item in config.approved_answers.items
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
        directory = (
            self._runtime_root
            / "candidates"
            / candidate_id
            / "application_archive"
            / str(application_id)
            / kind
        ).resolve()
        if not directory.is_relative_to(self._runtime_root):
            raise ApplicationConflictError("artifact path escaped runtime root")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        try:
            with path.open("xb") as output:
                output.write(content)
        except FileExistsError:
            if path.read_bytes() != content:
                raise ApplicationConflictError(
                    "immutable artifact version already exists"
                ) from None
        return path

    def _create_archive(
        self,
        session: Session,
        config: CandidateConfig,
        application: Application,
        job: GlobalJob | None,
        score: CandidateJobScore | None,
        documents: Sequence[ApplicationDocument],
        answers: Sequence[ApplicationAnswer],
    ) -> Path:
        events = session.scalars(
            select(ApplicationEvent).where(
                ApplicationEvent.candidate_id == application.candidate_id,
                ApplicationEvent.application_id == application.id,
            )
        ).all()
        archive = self._archives.create(
            candidate_id=application.candidate_id,
            application_id=application.id,
            data=ApplicationArchiveData(
                candidate_snapshot=config.model_dump(mode="json"),
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
                        "kind": item.kind.value,
                        "version": item.version,
                        "sha256": item.sha256,
                        "storage_uri": item.storage_uri,
                    }
                    for item in documents
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
                validation_report={"documents_valid": all(item.validated for item in documents)},
                event_log=[
                    {
                        "event_type": item.event_type,
                        "occurred_at": item.occurred_at,
                        "payload": item.payload,
                    }
                    for item in events
                ],
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
        for document in documents:
            session.add(
                ApplicationArtifact(
                    candidate_id=application.candidate_id,
                    application_id=application.id,
                    kind=document.kind.value,
                    version=document.version,
                    storage_uri=document.storage_uri,
                    sha256=document.sha256,
                    content_type="text/plain",
                    immutable=True,
                    artifact_metadata={"submitted_exact": True},
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
    def _settings_record(session: Session, candidate_id: str) -> CandidateSettingsRecord:
        record = session.scalar(
            select(CandidateSettingsRecord).where(
                CandidateSettingsRecord.candidate_id == candidate_id
            )
        )
        if record is None:
            record = CandidateSettingsRecord(candidate_id=candidate_id)
            session.add(record)
            session.flush()
        return record

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
            autonomy_blockers=tuple(blockers),
        )
