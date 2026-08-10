from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.applications.contracts import (
    AnalyticsOverview,
    AnswerRevisionRequest,
    AnswerView,
    ApplicationDetail,
    ApplicationMaterialPolicy,
    ApplicationSummary,
    ArtifactView,
    AuthorizationView,
    AutonomyConfirmationRequest,
    AutonomyPrerequisiteView,
    CorrespondenceIngestRequest,
    CorrespondenceView,
    DocumentView,
    DryRunCommand,
    EventView,
    HumanActionView,
    MaterialRevisionRequest,
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
from app.browser import (
    BrowserExecutor,
    BrowserFailureCategory,
    BrowserWorkerFailure,
    PlaywrightDryRunRequest,
    PlaywrightDryRunResult,
    UploadArtifact,
)
from app.browser.evidence import (
    BrowserAttemptManifest,
    BrowserEvidenceError,
    BrowserEvidenceStore,
    StoredBrowserEvidence,
)
from app.candidates.models import CandidateConfig, ClaimFact, ExperienceItem, ProjectItem
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
    AtsAdapterAcceptanceRecord,
    BrowserSession,
    CandidateJobScore,
    CandidateSettingsRecord,
    CandidateSnapshotRecord,
    ControlledSubmissionAttempt,
    GlobalJob,
    HumanAction,
    JobVersion,
    NotificationRecord,
    SecurityEvent,
    SubmissionAuthorizationRecord,
    WorkflowTask,
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
    AnswerReviewIdentity,
    ApprovedAnswerFact,
    ApprovedFact,
    Claim,
    DocumentGenerationAgent,
    GeneratedAnswer,
    GeneratedDocument,
    GenerationRequest,
    GenerationResult,
    IndependentReviewAgent,
    JobTarget,
    MaterialAgentProvenance,
    MaterialReview,
    RenderValidationReport,
)
from app.operations import AuthorizationConsumer
from app.submission import (
    ControlledAuthorizationRequest,
    ControlledGreenhouseFormPayload,
    ControlledSubmissionCommand,
    ControlledSubmissionError,
    ControlledSubmissionExecutionView,
    ControlledSubmissionExecutor,
    ControlledSubmissionPreparationRequest,
    ControlledSubmissionRequest,
    ControlledSubmissionResult,
    ControlledSubmissionUncertainError,
    GreenhouseControlledAdapter,
    PreparedControlledSubmission,
    SyntheticAdapterAcceptanceResult,
    SyntheticGreenhouseAcceptanceRunner,
)
from app.submission_gate import (
    FinalClickPermit,
    FinalClickProof,
    SubmissionGate,
    SubmissionGateInput,
)
from app.tasks import TaskLeaseLostError, TaskQueue, TaskView
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
    _AUTONOMY_CONSEQUENCE_VERSION = "autonomy-consequences-v1"

    @staticmethod
    def _material_policy(application: Application) -> ApplicationMaterialPolicy:
        try:
            return ApplicationMaterialPolicy.model_validate(application.material_policy)
        except ValueError as exc:
            raise ApplicationConflictError(
                "application material policy is missing or invalid"
            ) from exc

    @classmethod
    def _cover_letter_included(cls, application: Application) -> bool:
        return cls._material_policy(application).cover_letter.included

    @staticmethod
    def _material_policy_view(application: Application) -> ApplicationMaterialPolicy | None:
        try:
            return ApplicationMaterialPolicy.model_validate(application.material_policy)
        except ValueError:
            return None

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        candidate_service: CandidateService,
        runtime_root: Path,
        synthetic_confirmation: Callable[[str, UUID], str | None] | None = None,
        human_action_session_verifier: Callable[[str, UUID, UUID, Path], bool] | None = None,
        source_verifier: JobSourceVerifier | None = None,
        controlled_submission_enabled: bool = False,
        document_generation_agent: DocumentGenerationAgent | None = None,
        independent_review_agent: IndependentReviewAgent | None = None,
    ) -> None:
        self._sessions = session_factory
        self._candidates = candidate_service
        self._runtime_root = runtime_root.resolve()
        self._generator = document_generation_agent or DeterministicMaterialGenerator()
        self._generator_provenance = self._require_agent_provenance(
            self._generator, "document generation"
        )
        self._renderer = DeterministicPdfRenderer()
        self._reviewer = independent_review_agent or IndependentMaterialReviewer()
        self._reviewer_provenance = self._require_agent_provenance(
            self._reviewer, "independent review"
        )
        self._tasks = TaskQueue(session_factory)
        self._browser_evidence = BrowserEvidenceStore(self._runtime_root)
        self._archives = ApplicationArchiveBuilder(self._runtime_root / "application_archive")
        self._consumer = AuthorizationConsumer(session_factory)
        self._correspondence = CorrespondenceService()
        self._source_verifier = source_verifier or ProviderJobSourceVerifier()
        self._controlled_submission_enabled = controlled_submission_enabled
        self._synthetic_confirmation = synthetic_confirmation or (
            lambda _candidate_id, application_id: f"synthetic-confirmation-{application_id}"
        )
        self._human_action_session_verifier = human_action_session_verifier or (
            lambda _candidate_id, _application_id, _session_id, _session_path: False
        )

    @staticmethod
    def _require_agent_provenance(
        agent: DocumentGenerationAgent | IndependentReviewAgent,
        role: str,
    ) -> MaterialAgentProvenance:
        try:
            return MaterialAgentProvenance.model_validate(agent.provenance)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError(f"{role} agent must declare valid immutable provenance") from exc

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
            try:
                material_config = CandidateConfig.model_validate_json(snapshot.config_json)
            except ValueError as exc:
                raise ApplicationConflictError(
                    "candidate snapshot configuration is invalid"
                ) from exc
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
            request = self._generation_request(material_config, application.id, job)
            job_version = session.scalar(
                select(JobVersion)
                .where(JobVersion.job_id == job.id)
                .order_by(JobVersion.version.desc())
                .limit(1)
            )
            if job_version is None:
                raise ApplicationConflictError("material generation requires a job snapshot")
            material_policy = self._build_material_policy(request, material_config, job_version)
            application.material_policy = material_policy.model_dump(mode="json")
            score.rationale = {
                **score.rationale,
                "selected_experience": list(request.selected_experience_ids),
                "selected_projects": list(request.selected_project_ids),
                "material_policy": material_policy.model_dump(mode="json"),
            }
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
                        request.cv_template_id,
                        material_config.cv_rules.template_version,
                    )[0],
                    template_version=template_for(
                        document.kind,
                        request.cv_template_id,
                        material_config.cv_rules.template_version,
                    )[1],
                    maximum_pages=(
                        material_config.cv_rules.max_pages
                        if document.kind is DocumentKind.CV
                        else 2
                    ),
                    document_version=document_versions[document.kind],
                )
                for document in generated.documents
            )
            previous_answers = {
                answer.question_key: answer
                for answer in self._latest_answers(
                    session, candidate_id, application.id, include_withdrawn=True
                )
            }
            answer_rows: list[ApplicationAnswer] = []
            generated_keys: set[str] = set()
            for answer in generated.answers:
                generated_keys.add(answer.question_key)
                previous = previous_answers.get(answer.question_key)
                approved_answer = next(
                    (
                        item
                        for item in request.approved_answers
                        if item.key == answer.question_key
                        and item.question_pattern == answer.question
                        and item.answer == answer.answer
                    ),
                    None,
                )
                answer_rows.append(
                    ApplicationAnswer(
                        id=uuid4(),
                        candidate_id=candidate_id,
                        application_id=application.id,
                        question_key=answer.question_key,
                        question=answer.question,
                        answer=answer.answer,
                        version=(previous.version + 1 if previous is not None else 1),
                        sha256=self._answer_sha256(answer.answer),
                        actor_id="material-generator",
                        revision_kind="generated",
                        previous_answer_id=previous.id if previous is not None else None,
                        candidate_snapshot_id=snapshot_record.id,
                        candidate_snapshot_version=snapshot_record.profile_version,
                        candidate_snapshot_sha256=snapshot_record.sha256,
                        approved_source_key=(
                            approved_answer.key if approved_answer is not None else None
                        ),
                        evidence_ids={
                            "items": list(approved_answer.evidence_ids) if approved_answer else []
                        },
                        supported=approved_answer is not None,
                    )
                )
            for question_key, previous in previous_answers.items():
                if question_key in generated_keys or previous.revision_kind == "withdrawn":
                    continue
                withdrawn = "[withdrawn]"
                answer_rows.append(
                    ApplicationAnswer(
                        id=uuid4(),
                        candidate_id=candidate_id,
                        application_id=application.id,
                        question_key=question_key,
                        question=previous.question,
                        answer=withdrawn,
                        version=previous.version + 1,
                        sha256=self._answer_sha256(withdrawn),
                        actor_id="material-generator",
                        revision_kind="withdrawn",
                        previous_answer_id=previous.id,
                        candidate_snapshot_id=snapshot_record.id,
                        candidate_snapshot_version=snapshot_record.profile_version,
                        candidate_snapshot_sha256=snapshot_record.sha256,
                        evidence_ids={"items": []},
                        supported=False,
                    )
                )
            active_answer_rows = tuple(
                sorted(
                    (row for row in answer_rows if row.revision_kind != "withdrawn"),
                    key=lambda row: row.question_key,
                )
            )
            generated = generated.model_copy(
                update={"answers": tuple(self._generated_answer(row) for row in active_answer_rows)}
            )
            review = self._reviewer.review(
                request, generated, tuple(item.report for item in rendered)
            ).model_copy(
                update={"answer_reports": self._answer_review_identities(active_answer_rows)}
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
                approved_fact_sources = {
                    fact.fact_id: fact.source_path for fact in request.approved_facts
                }
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
                    "manual_revision": False,
                    "actor_id": "material-generator",
                    "provenance": [
                        {
                            "text": claim.text,
                            "evidence_ids": list(claim.evidence_ids),
                            "source_paths": [
                                approved_fact_sources[item] for item in claim.evidence_ids
                            ],
                        }
                        for claim in document.claims
                    ],
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
            session.add_all(answer_rows)
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

    def authorize_controlled(
        self,
        candidate_id: str,
        application_id: UUID,
        request: ControlledAuthorizationRequest,
        idempotency_key: str,
    ) -> AuthorizationView:
        """Bind a gate authorization to one exact controlled adapter and destination."""

        return self._authorize_controlled(
            candidate_id,
            application_id,
            approval_acknowledged=request.approval_acknowledged,
            consequence_version=request.consequence_version,
            idempotency_key=idempotency_key,
        )

    def _authorize_controlled(
        self,
        candidate_id: str,
        application_id: UUID,
        *,
        approval_acknowledged: bool,
        consequence_version: str | None,
        idempotency_key: str,
    ) -> AuthorizationView:

        with self._candidates.lifecycle_write(candidate_id):
            if not self._controlled_submission_enabled:
                raise ApplicationConflictError("controlled submission is disabled")
            config = self._candidates.get_config(candidate_id)
            with self._sessions() as lookup:
                application = self._application(lookup, candidate_id, application_id)
                job = lookup.get(GlobalJob, application.job_id)
                settings = self._settings_record(lookup, candidate_id)
                target_url = self._validate_controlled_policy(
                    lookup,
                    config,
                    settings,
                    job,
                    approval_acknowledged=approval_acknowledged,
                )
            view = self._authorize(candidate_id, application_id, idempotency_key)
            target_sha256 = hashlib.sha256(target_url.encode()).hexdigest()
            with self._sessions.begin() as session:
                application = self._application(session, candidate_id, application_id)
                record = session.get(SubmissionAuthorizationRecord, view.authorization_id)
                if (
                    record is None
                    or record.candidate_id != candidate_id
                    or record.application_id != application_id
                    or record.consumed_at is not None
                ):
                    raise ApplicationConflictError("submission authorization was not found")
                if record.execution_mode not in {"synthetic", "controlled"}:
                    raise ApplicationConflictError("submission authorization mode is invalid")
                if record.execution_mode == "controlled" and (
                    record.adapter != "greenhouse_controlled_v1"
                    or record.target_url_sha256 != target_sha256
                    or record.authorized_state_version != application.state_version
                ):
                    raise ApplicationConflictError(
                        "controlled authorization does not match the current application"
                    )
                record.execution_mode = "controlled"
                record.adapter = "greenhouse_controlled_v1"
                record.target_url_sha256 = target_sha256
                record.authorized_state_version = application.state_version
                browser_session = session.scalar(
                    select(BrowserSession).where(
                        BrowserSession.candidate_id == candidate_id,
                        BrowserSession.application_id == application_id,
                    )
                )
                if browser_session is not None:
                    browser_session.authorization_id = record.authorization_id
                self._append_same_state_event(
                    session,
                    application,
                    f"{idempotency_key}:controlled",
                    "CONTROLLED_SUBMISSION_AUTHORIZED",
                    payload={
                        "authorization_id": str(record.authorization_id),
                        "adapter": record.adapter,
                        "target_url_sha256": target_sha256,
                        "approval_actor": (
                            "local-user" if approval_acknowledged else "autonomous-policy"
                        ),
                        "approval_acknowledged": approval_acknowledged,
                        "consequence_version": consequence_version,
                    },
                )
            return view

    def enqueue_autonomous_controlled_submissions(
        self, candidate_id: str
    ) -> tuple[ControlledSubmissionExecutionView, ...]:
        """Queue ready tested patterns only when autonomous policy is fully enabled."""

        if not self._controlled_submission_enabled:
            return ()
        config = self._candidates.get_config(candidate_id)
        with self._sessions() as session:
            settings = session.scalar(
                select(CandidateSettingsRecord).where(
                    CandidateSettingsRecord.candidate_id == candidate_id
                )
            )
            if (
                settings is None
                or settings.automation_mode != "autonomous"
                or self._settings_view(session, config, settings).autonomy_blockers
            ):
                return ()
            ready = tuple(
                session.execute(
                    select(Application.id, Application.state_version)
                    .where(
                        Application.candidate_id == candidate_id,
                        Application.state == ApplicationState.READY_TO_SUBMIT,
                        ~exists(
                            select(ControlledSubmissionAttempt.id).where(
                                ControlledSubmissionAttempt.candidate_id == candidate_id,
                                ControlledSubmissionAttempt.application_id == Application.id,
                            )
                        ),
                    )
                    .order_by(Application.updated_at, Application.id)
                ).all()
            )
        queued: list[ControlledSubmissionExecutionView] = []
        for application_id, state_version in ready:
            key_suffix = f"{application_id}:{state_version}"
            try:
                authorization = self._authorize_controlled(
                    candidate_id,
                    application_id,
                    approval_acknowledged=False,
                    consequence_version=None,
                    idempotency_key=f"autonomous-controlled-authorize:{key_suffix}",
                )
                queued.append(
                    self.queue_controlled_submission(
                        candidate_id,
                        application_id,
                        ControlledSubmissionCommand(
                            authorization_id=authorization.authorization_id
                        ),
                        f"autonomous-controlled-queue:{key_suffix}",
                    )
                )
            except ApplicationConflictError:
                continue
        return tuple(queued)

    def queue_controlled_submission(
        self,
        candidate_id: str,
        application_id: UUID,
        command: ControlledSubmissionCommand,
        idempotency_key: str,
    ) -> ControlledSubmissionExecutionView:
        """Queue a one-attempt isolated final-click task without performing browser I/O."""

        if not self._controlled_submission_enabled:
            raise ApplicationConflictError("controlled submission is disabled")
        with self._candidates.lifecycle_write(candidate_id), self._sessions.begin() as session:
            payload = {
                "application_id": str(application_id),
                "authorization_id": str(command.authorization_id),
            }
            replay, request_sha256, key_sha256 = self._administrative_command_replay(
                session,
                candidate_id,
                "queue_controlled_submission",
                payload,
                idempotency_key,
            )
            if replay is not None:
                return ControlledSubmissionExecutionView.model_validate(replay)
            config = self._candidates.get_config(candidate_id)
            application = self._application(session, candidate_id, application_id)
            record = session.get(SubmissionAuthorizationRecord, command.authorization_id)
            now = datetime.now(UTC)
            if (
                record is None
                or record.candidate_id != candidate_id
                or record.application_id != application_id
                or record.execution_mode != "controlled"
                or record.adapter != "greenhouse_controlled_v1"
                or record.consumed_at is not None
                or now < _utc(record.issued_at)
                or now >= _utc(record.expires_at)
                or record.authorized_state_version != application.state_version
            ):
                raise ApplicationConflictError("controlled authorization is invalid or expired")
            job = session.get(GlobalJob, application.job_id)
            settings = self._settings_record(session, candidate_id)
            target_url = self._validate_controlled_policy(
                session, config, settings, job, approval_acknowledged=True
            )
            assert job is not None
            if record.target_url_sha256 is None or not hmac.compare_digest(
                record.target_url_sha256, hashlib.sha256(target_url.encode()).hexdigest()
            ):
                raise ApplicationConflictError("controlled submission target changed")
            browser_session = session.scalar(
                select(BrowserSession).where(
                    BrowserSession.candidate_id == candidate_id,
                    BrowserSession.application_id == application_id,
                )
            )
            if browser_session is None or browser_session.status != "ready":
                raise ApplicationConflictError("controlled browser session is not ready")
            existing = session.scalar(
                select(ControlledSubmissionAttempt)
                .where(
                    ControlledSubmissionAttempt.candidate_id == candidate_id,
                    ControlledSubmissionAttempt.application_id == application_id,
                    ControlledSubmissionAttempt.status != "denied",
                )
                .order_by(
                    ControlledSubmissionAttempt.created_at.desc(),
                    ControlledSubmissionAttempt.id.desc(),
                )
                .limit(1)
            )
            if existing is not None:
                if existing.authorization_id != record.authorization_id:
                    raise ApplicationConflictError(
                        "application already has a controlled submission execution"
                    )
                return self._controlled_submission_view(application, existing)
            attempt = ControlledSubmissionAttempt(
                candidate_id=candidate_id,
                application_id=application_id,
                authorization_id=record.authorization_id,
                browser_session_id=browser_session.id,
                adapter="greenhouse_controlled_v1",
                target_url=target_url,
                target_origin=self._safe_origin(target_url),
                package_sha256=record.package_sha256 or "",
                status="prepared",
            )
            session.add(attempt)
            session.flush()
            task = self._tasks.enqueue_in_session(
                session,
                candidate_id=candidate_id,
                kind="controlled_submission",
                idempotency_key=(
                    f"controlled:{application_id}:"
                    f"{hashlib.sha256(idempotency_key.encode()).hexdigest()}"
                ),
                payload={
                    "application_id": str(application_id),
                    "attempt_id": str(attempt.id),
                },
                max_attempts=1,
            )
            attempt.task_id = task.task_id
            self._append_same_state_event(
                session,
                application,
                f"controlled-task:{task.task_id}:queued",
                "CONTROLLED_SUBMISSION_QUEUED",
                payload={"attempt_id": str(attempt.id), "task_id": str(task.task_id)},
            )
            session.flush()
            view = self._controlled_submission_view(application, attempt)
            self._append_administrative_command_receipt(
                session,
                candidate_id,
                "queue_controlled_submission",
                key_sha256,
                request_sha256,
                view.model_dump(mode="json"),
            )
            return view

    def execute_controlled_submission_task(
        self,
        queue: TaskQueue,
        task: TaskView,
        *,
        worker_id: str,
        executor: ControlledSubmissionExecutor,
        now: datetime | None = None,
    ) -> TaskView:
        """Prepare, durably arm, and dispatch exactly one controlled final click."""

        if task.kind != "controlled_submission" or task.attempts != 1:
            raise ApplicationConflictError("controlled submission task lease is invalid")
        with self._candidates.lifecycle_write(task.candidate_id):
            return self._execute_controlled_submission_task_locked(
                queue,
                task,
                worker_id=worker_id,
                executor=executor,
                now=now,
            )

    def _execute_controlled_submission_task_locked(
        self,
        queue: TaskQueue,
        task: TaskView,
        *,
        worker_id: str,
        executor: ControlledSubmissionExecutor,
        now: datetime | None,
    ) -> TaskView:
        started_at = now or datetime.now(UTC)
        armed = False
        try:
            preparation_request, job_id = self._controlled_preparation_request(task)
            prepared = executor.prepare(preparation_request)
            self._validate_controlled_preparation(preparation_request, prepared)
            pre_click_paths = self._store_controlled_pre_click_evidence(
                preparation_request, prepared
            )
            self._revalidate_job(job_id)
            click_nonce = secrets.token_bytes(32)
            click_request = self._arm_controlled_submission(
                queue,
                task,
                worker_id=worker_id,
                preparation_request=preparation_request,
                prepared=prepared,
                pre_click_paths=pre_click_paths,
                click_nonce=click_nonce,
                now=datetime.now(UTC),
            )
            armed = True
            permit = self._controlled_click_permit(click_request, click_nonce)
            result = executor.execute(click_request, permit)
            if result.attempt_id != click_request.attempt_id or not result.confirmation_detected:
                return self._mark_controlled_unknown(
                    queue,
                    task,
                    worker_id=worker_id,
                    category="confirmation_missing",
                    now=datetime.now(UTC),
                )
            return self._confirm_controlled_submission(
                queue,
                task,
                worker_id=worker_id,
                result=result,
                now=datetime.now(UTC),
            )
        except Exception as exc:
            executor.abort()
            if isinstance(exc, ControlledSubmissionUncertainError):
                category = "uncertain_after_click"
            elif isinstance(exc, ControlledSubmissionError):
                category = exc.category
            else:
                category = type(exc).__name__
            if armed:
                return self._mark_controlled_unknown(
                    queue,
                    task,
                    worker_id=worker_id,
                    category=category,
                    now=datetime.now(UTC),
                )
            return self._deny_controlled_before_click(
                queue,
                task,
                worker_id=worker_id,
                category=category,
                human_action_kind=(
                    exc.human_action_kind if isinstance(exc, ControlledSubmissionError) else None
                ),
                now=started_at,
            )

    def _controlled_preparation_request(
        self, task: TaskView
    ) -> tuple[ControlledSubmissionPreparationRequest, UUID]:
        try:
            attempt_id = UUID(str(task.payload["attempt_id"]))
            application_id = UUID(str(task.payload["application_id"]))
        except (KeyError, ValueError) as exc:
            raise ApplicationConflictError("controlled submission task payload is invalid") from exc
        with self._sessions() as session:
            application = self._application(session, task.candidate_id, application_id)
            attempt = session.get(ControlledSubmissionAttempt, attempt_id)
            if (
                attempt is None
                or attempt.candidate_id != task.candidate_id
                or attempt.application_id != application_id
                or attempt.task_id != task.task_id
                or attempt.status != "prepared"
            ):
                raise ApplicationConflictError("controlled submission attempt is not preparable")
            review = session.scalar(
                select(AgentReview)
                .where(
                    AgentReview.candidate_id == task.candidate_id,
                    AgentReview.application_id == application_id,
                )
                .order_by(AgentReview.created_at.desc(), AgentReview.id.desc())
                .limit(1)
            )
            if review is None:
                raise ApplicationConflictError("reviewed controlled form package is missing")
            form_payload = self._controlled_form_payload(session, application, review)
            return (
                ControlledSubmissionPreparationRequest(
                    attempt_id=attempt.id,
                    candidate_id=task.candidate_id,
                    application_id=application_id,
                    authorization_id=attempt.authorization_id,
                    browser_session_id=attempt.browser_session_id,
                    target_url=attempt.target_url,
                    form=form_payload,
                ),
                application.job_id,
            )

    def _controlled_form_payload(
        self, session: Session, application: Application, review: AgentReview
    ) -> ControlledGreenhouseFormPayload:
        reviewed_materials = self._reviewed_materials(session, application, review)
        snapshot_record = self._reviewed_snapshot(session, application, reviewed_materials)
        snapshot = self._load_candidate_snapshot(application, snapshot_record)
        try:
            snapshot_config = CandidateConfig.model_validate_json(snapshot.config_json)
        except ValueError as exc:
            raise ApplicationConflictError("controlled form candidate snapshot is invalid") from exc
        name_parts = snapshot_config.identity.full_name.split(maxsplit=1)
        if len(name_parts) != 2 or not all(name_parts):
            raise ApplicationConflictError(
                "controlled Greenhouse submission requires a reviewed first and last name"
            )
        rendered_cv = next(
            artifact
            for document, artifact in reviewed_materials
            if document.kind is DocumentKind.CV
        )
        return ControlledGreenhouseFormPayload(
            first_name=name_parts[0],
            last_name=name_parts[1],
            email=snapshot_config.identity.email,
            resume_path=Path(rendered_cv.storage_uri),
            resume_sha256=rendered_cv.sha256,
        )

    @staticmethod
    def _validate_controlled_preparation(
        request: ControlledSubmissionPreparationRequest,
        prepared: PreparedControlledSubmission,
    ) -> None:
        if (
            prepared.attempt_id != request.attempt_id
            or prepared.inspection.target_url != request.target_url
            or prepared.inspection.human_verification_present
            or prepared.form_payload_sha256 != request.form.sha256()
        ):
            raise ControlledSubmissionError("controlled page preparation changed scope")

    def _arm_controlled_submission(
        self,
        queue: TaskQueue,
        task: TaskView,
        *,
        worker_id: str,
        preparation_request: ControlledSubmissionPreparationRequest,
        prepared: PreparedControlledSubmission,
        pre_click_paths: tuple[Path, Path],
        click_nonce: bytes,
        now: datetime,
    ) -> ControlledSubmissionRequest:
        with self._sessions.begin() as session:
            queue.assert_lease_in_session(
                session,
                task.task_id,
                worker_id=worker_id,
                expected_attempt=task.attempts,
            )
            attempt = session.scalar(
                select(ControlledSubmissionAttempt)
                .where(ControlledSubmissionAttempt.id == prepared.attempt_id)
                .with_for_update()
            )
            if (
                attempt is None
                or attempt.candidate_id != task.candidate_id
                or attempt.task_id != task.task_id
                or attempt.status != "prepared"
            ):
                raise ApplicationConflictError("controlled submission attempt cannot be armed")
            application = self._application(session, task.candidate_id, attempt.application_id)
            record = session.get(SubmissionAuthorizationRecord, attempt.authorization_id)
            if (
                record is None
                or record.candidate_id != task.candidate_id
                or record.application_id != application.id
                or record.execution_mode != "controlled"
                or record.adapter != attempt.adapter
                or record.consumed_at is not None
                or now < _utc(record.issued_at)
                or now >= _utc(record.expires_at)
                or application.state is not ApplicationState.READY_TO_SUBMIT
                or record.authorized_state_version != application.state_version
            ):
                raise ApplicationConflictError(
                    "controlled authorization cannot cross click boundary"
                )
            config = self._candidates.get_config(task.candidate_id)
            job = session.get(GlobalJob, application.job_id)
            settings = self._settings_record(session, task.candidate_id)
            target_url = self._validate_controlled_policy(
                session, config, settings, job, approval_acknowledged=True
            )
            assert job is not None
            target_sha256 = hashlib.sha256(target_url.encode()).hexdigest()
            if (
                target_url != attempt.target_url
                or record.target_url_sha256 is None
                or not hmac.compare_digest(record.target_url_sha256, target_sha256)
                or not self._job_is_fresh(job, now, self._SUBMISSION_FRESHNESS)
            ):
                raise ApplicationConflictError("controlled submission source changed before click")
            if application.submission_identity_hash is None:
                raise ApplicationConflictError("application duplicate identity is missing")
            duplicate = session.scalar(
                select(func.count(Application.id)).where(
                    Application.candidate_id == task.candidate_id,
                    Application.submission_identity_hash == application.submission_identity_hash,
                    Application.id != application.id,
                )
            )
            if duplicate:
                raise ApplicationConflictError("candidate has an equivalent application")
            review = session.scalar(
                select(AgentReview)
                .where(
                    AgentReview.candidate_id == task.candidate_id,
                    AgentReview.application_id == application.id,
                )
                .order_by(AgentReview.created_at.desc(), AgentReview.id.desc())
                .limit(1)
            )
            if review is None:
                raise ApplicationConflictError("material review is missing")
            reviewed_materials = self._reviewed_materials(session, application, review)
            snapshot = self._reviewed_snapshot(session, application, reviewed_materials)
            upload_hashes = self._browser_upload_hashes(session, application)
            rendered_cv = next(
                artifact
                for _document, artifact in reviewed_materials
                if artifact.kind == "rendered_cv"
            )
            if upload_hashes != (rendered_cv.sha256,):
                raise ApplicationConflictError("browser upload changed before click")
            package_sha256 = self._submission_package_sha256(
                application, reviewed_materials, snapshot, upload_hashes
            )
            if (
                record.package_sha256 is None
                or not hmac.compare_digest(record.package_sha256, package_sha256)
                or not hmac.compare_digest(attempt.package_sha256, package_sha256)
            ):
                raise ApplicationConflictError("controlled submission package changed")
            browser_session = session.get(BrowserSession, attempt.browser_session_id)
            if (
                browser_session is None
                or browser_session.candidate_id != task.candidate_id
                or browser_session.application_id != application.id
                or browser_session.status != "ready"
                or browser_session.authorization_id != record.authorization_id
            ):
                raise ApplicationConflictError("controlled browser session changed")
            if settings.emergency_stopped or not self._rate_limits_allow(
                session, task.candidate_id, job.company, settings, now
            ):
                raise ApplicationConflictError("controlled submission policy stopped the click")
            current_adapter = GreenhouseControlledAdapter()
            exact_acceptance = any(
                item.adapter_version == current_adapter.VERSION
                and item.destination_policy_sha256 == current_adapter.destination_policy_sha256
                and item.form_fingerprint == prepared.inspection.form_fingerprint
                for item in self._valid_adapter_acceptances(session, task.candidate_id)
            )
            if not exact_acceptance:
                raise ApplicationConflictError(
                    "controlled form pattern has no current synthetic acceptance evidence"
                )
            claimed = session.execute(
                update(SubmissionAuthorizationRecord)
                .where(
                    SubmissionAuthorizationRecord.authorization_id == record.authorization_id,
                    SubmissionAuthorizationRecord.candidate_id == task.candidate_id,
                    SubmissionAuthorizationRecord.application_id == application.id,
                    SubmissionAuthorizationRecord.consumed_at.is_(None),
                )
                .values(consumed_at=now)
                .returning(SubmissionAuthorizationRecord.authorization_id)
            ).scalar_one_or_none()
            if claimed is None:
                raise ApplicationConflictError("controlled authorization was already consumed")
            screenshot_sha256 = hashlib.sha256(prepared.pre_click_screenshot_png).hexdigest()
            page_sha256 = hashlib.sha256(prepared.pre_click_page_html).hexdigest()
            attempt.form_fingerprint = prepared.inspection.form_fingerprint
            attempt.form_payload_sha256 = prepared.form_payload_sha256
            attempt.pre_click_screenshot_sha256 = screenshot_sha256
            attempt.pre_click_page_sha256 = page_sha256
            attempt.click_nonce_sha256 = hashlib.sha256(click_nonce).hexdigest()
            attempt.click_boundary_entered_at = now
            attempt.status = "click_authorized"
            for kind, path, digest, content_type in (
                (
                    "controlled_pre_submit_screenshot",
                    pre_click_paths[0],
                    screenshot_sha256,
                    "image/png",
                ),
                (
                    "controlled_pre_submit_page",
                    pre_click_paths[1],
                    page_sha256,
                    "text/html",
                ),
            ):
                session.add(
                    ApplicationArtifact(
                        candidate_id=task.candidate_id,
                        application_id=application.id,
                        kind=kind,
                        version=1,
                        storage_uri=str(path),
                        sha256=digest,
                        content_type=content_type,
                        immutable=True,
                        artifact_metadata={
                            "attempt_id": str(attempt.id),
                            "click_boundary": "pre_click",
                        },
                    )
                )
            self._transition(
                session,
                application,
                ApplicationState.SUBMITTING,
                f"controlled-task:{task.task_id}:armed",
                "CONTROLLED_SUBMISSION_CLICK_ARMED",
                payload={
                    "attempt_id": str(attempt.id),
                    "authorization_id": str(record.authorization_id),
                    "form_fingerprint": attempt.form_fingerprint,
                    "form_payload_sha256": attempt.form_payload_sha256,
                    "pre_click_screenshot_sha256": screenshot_sha256,
                    "pre_click_page_sha256": page_sha256,
                },
            )
            session.flush()
            return ControlledSubmissionRequest(
                attempt_id=attempt.id,
                candidate_id=task.candidate_id,
                application_id=application.id,
                authorization_id=record.authorization_id,
                target_url=target_url,
                package_sha256=package_sha256,
                form=ControlledGreenhouseFormPayload(
                    first_name=preparation_request.form.first_name,
                    last_name=preparation_request.form.last_name,
                    email=preparation_request.form.email,
                    resume_path=preparation_request.form.resume_path,
                    resume_sha256=preparation_request.form.resume_sha256,
                ),
                expected_form_payload_sha256=prepared.form_payload_sha256,
                expected_form_fingerprint=prepared.inspection.form_fingerprint,
            )

    def _controlled_click_permit(
        self, request: ControlledSubmissionRequest, click_nonce: bytes
    ) -> FinalClickPermit:
        with self._sessions() as session:
            attempt = session.get(ControlledSubmissionAttempt, request.attempt_id)
            application = self._application(session, request.candidate_id, request.application_id)
            record = session.get(SubmissionAuthorizationRecord, request.authorization_id)
            if attempt is None or record is None:
                raise ApplicationConflictError("committed click proof is missing")
            proof = FinalClickProof(
                candidate_id=request.candidate_id,
                application_id=request.application_id,
                authorization_id=request.authorization_id,
                attempt_id=request.attempt_id,
                application_state=application.state,
                attempt_status=attempt.status,
                authorization_consumed_at=record.consumed_at,
                click_boundary_entered_at=attempt.click_boundary_entered_at,
                click_nonce_sha256=attempt.click_nonce_sha256,
            )
        return SubmissionGate().issue_final_click_permit(proof, click_nonce)

    def revise_material(
        self,
        candidate_id: str,
        application_id: UUID,
        revision: MaterialRevisionRequest,
        idempotency_key: str,
    ) -> ApplicationDetail:
        with self._candidates.lifecycle_write(candidate_id), self._sessions.begin() as session:
            payload = revision.model_dump(mode="json")
            payload["application_id"] = str(application_id)
            replay, request_sha256, key_sha256 = self._administrative_command_replay(
                session, candidate_id, "revise_material", payload, idempotency_key
            )
            if replay is not None:
                return ApplicationDetail.model_validate(replay)
            application = self._application(session, candidate_id, application_id)
            if application.state not in {
                ApplicationState.REVIEW_PENDING,
                ApplicationState.REVIEW_FAILED,
            }:
                raise ApplicationConflictError(
                    "materials can only be revised while independent review is pending or failed"
                )
            base_document = session.scalar(
                select(ApplicationDocument).where(
                    ApplicationDocument.id == revision.document_id,
                    ApplicationDocument.candidate_id == candidate_id,
                    ApplicationDocument.application_id == application_id,
                )
            )
            if base_document is None:
                raise ApplicationConflictError("material revision target was not found")
            latest_version = session.scalar(
                select(func.max(ApplicationDocument.version)).where(
                    ApplicationDocument.candidate_id == candidate_id,
                    ApplicationDocument.application_id == application_id,
                    ApplicationDocument.kind == base_document.kind,
                )
            )
            if (
                latest_version is None
                or base_document.version != latest_version
                or revision.base_version != latest_version
            ):
                raise ApplicationConflictError("material revision base version is stale")
            if not self._source_document_valid(base_document):
                raise ApplicationConflictError("material revision source is missing or corrupted")
            if Path(base_document.storage_uri).read_text(encoding="utf-8") == revision.content:
                raise ApplicationConflictError("material revision must change the selected facts")

            job = session.get(GlobalJob, application.job_id)
            if job is None:
                raise ApplicationConflictError("application job is missing")
            persisted_policy = self._material_policy(application)
            latest_job_version = session.scalar(
                select(JobVersion)
                .where(JobVersion.job_id == job.id)
                .order_by(JobVersion.version.desc())
                .limit(1)
            )
            if (
                latest_job_version is None
                or latest_job_version.version != persisted_policy.job_version
                or latest_job_version.payload_sha256 != persisted_policy.job_payload_sha256
            ):
                raise ApplicationConflictError(
                    "material revision requires the original unchanged job snapshot"
                )
            base_report = session.scalar(
                select(ApplicationArtifact).where(
                    ApplicationArtifact.candidate_id == candidate_id,
                    ApplicationArtifact.application_id == application_id,
                    ApplicationArtifact.kind == f"render_report_{base_document.kind.value}",
                    ApplicationArtifact.version == base_document.version,
                )
            )
            if base_report is None or not self._render_report_artifact_valid(
                base_report, document=base_document
            ):
                raise ApplicationConflictError("material render report is missing or corrupted")
            try:
                snapshot_id = UUID(str(base_report.artifact_metadata["candidate_snapshot_id"]))
            except (KeyError, ValueError) as exc:
                raise ApplicationConflictError("material snapshot identity is invalid") from exc
            snapshot_record = session.get(CandidateSnapshotRecord, snapshot_id)
            if (
                snapshot_record is None
                or snapshot_record.candidate_id != candidate_id
                or snapshot_record.application_id != application_id
                or base_report.artifact_metadata.get("candidate_snapshot_version")
                != snapshot_record.profile_version
                or base_report.artifact_metadata.get("candidate_snapshot_sha256")
                != snapshot_record.sha256
            ):
                raise ApplicationConflictError("material snapshot identity is invalid")
            snapshot = self._load_candidate_snapshot(application, snapshot_record)
            try:
                snapshot_config = CandidateConfig.model_validate_json(snapshot.config_json)
            except ValueError as exc:
                raise ApplicationConflictError(
                    "candidate snapshot configuration is invalid"
                ) from exc
            generation_request = self._generation_request(snapshot_config, application_id, job)
            recomputed_policy = self._build_material_policy(
                generation_request, snapshot_config, latest_job_version
            )
            if recomputed_policy != persisted_policy:
                raise ApplicationConflictError(
                    "material revision policy no longer matches the reviewed application"
                )
            if base_document.kind not in generation_request.requested_documents:
                raise ApplicationConflictError(
                    "material kind is not enabled by the candidate snapshot"
                )
            revised_document = self._manual_document(
                base_document.kind,
                revision.content,
                generation_request,
                reject_duplicate_claims=True,
            )

            all_documents = session.scalars(
                select(ApplicationDocument)
                .where(
                    ApplicationDocument.candidate_id == candidate_id,
                    ApplicationDocument.application_id == application_id,
                )
                .order_by(ApplicationDocument.version.desc())
            ).all()
            latest_by_kind: dict[DocumentKind, ApplicationDocument] = {}
            for document in all_documents:
                latest_by_kind.setdefault(document.kind, document)
            canonical_by_kind = {
                document.kind: document
                for document in self._generator.generate(generation_request).documents
            }
            generated_documents: list[GeneratedDocument] = []
            document_versions: dict[DocumentKind, int] = {}
            for kind in generation_request.requested_documents:
                stored = latest_by_kind.get(kind)
                if stored is None or not self._source_document_valid(stored):
                    raise ApplicationConflictError(
                        f"latest {kind.value} source is missing or corrupted"
                    )
                document_versions[kind] = (
                    stored.version + 1 if kind is base_document.kind else stored.version
                )
                if kind is not base_document.kind:
                    peer_artifact = session.scalar(
                        select(ApplicationArtifact).where(
                            ApplicationArtifact.candidate_id == candidate_id,
                            ApplicationArtifact.application_id == application_id,
                            ApplicationArtifact.kind == f"rendered_{kind.value}",
                            ApplicationArtifact.version == stored.version,
                        )
                    )
                    if peer_artifact is None or not self._render_artifact_valid(
                        peer_artifact,
                        document=stored,
                        snapshot=snapshot_record,
                    ):
                        raise ApplicationConflictError(
                            f"latest {kind.value} render is missing or corrupted"
                        )
                stored_content = Path(stored.storage_uri).read_text(encoding="utf-8")
                canonical = canonical_by_kind[kind]
                generated_documents.append(
                    revised_document
                    if kind is base_document.kind
                    else (
                        canonical
                        if stored_content == canonical.content
                        else self._manual_document(
                            kind,
                            stored_content,
                            generation_request,
                            reject_duplicate_claims=False,
                        )
                    )
                )
            stored_answers = self._latest_answers(session, candidate_id, application_id)
            generated_answers = tuple(self._generated_answer(answer) for answer in stored_answers)
            generated = GenerationResult(
                candidate_id=candidate_id,
                application_id=application_id,
                target=generation_request.target,
                documents=tuple(generated_documents),
                answers=generated_answers,
            )
            rendered = tuple(
                self._renderer.render(
                    document,
                    template_id=template_for(
                        document.kind,
                        generation_request.cv_template_id,
                        snapshot_config.cv_rules.template_version,
                    )[0],
                    template_version=template_for(
                        document.kind,
                        generation_request.cv_template_id,
                        snapshot_config.cv_rules.template_version,
                    )[1],
                    maximum_pages=(
                        snapshot_config.cv_rules.max_pages
                        if document.kind is DocumentKind.CV
                        else 2
                    ),
                    document_version=document_versions[document.kind],
                )
                for document in generated.documents
            )
            review = self._reviewer.review(
                generation_request, generated, tuple(item.report for item in rendered)
            ).model_copy(update={"answer_reports": self._answer_review_identities(stored_answers)})
            revised_render = next(
                item for item in rendered if item.document.kind is base_document.kind
            )
            new_version = document_versions[base_document.kind]
            evidence_ids = sorted(
                {evidence for claim in revised_document.claims for evidence in claim.evidence_ids}
            )
            document_path = self._write_exclusive(
                candidate_id,
                application_id,
                base_document.kind.value,
                f"v{new_version}.txt",
                revised_document.content.encode("utf-8"),
            )
            new_document = ApplicationDocument(
                candidate_id=candidate_id,
                application_id=application_id,
                kind=base_document.kind,
                version=new_version,
                storage_uri=str(document_path),
                sha256=revised_document.content_sha256,
                evidence_ids={"items": evidence_ids},
                validated=review.documents_supported and revised_render.report.valid,
            )
            session.add(new_document)
            session.flush()
            fact_sources = {
                fact.fact_id: fact.source_path for fact in generation_request.approved_facts
            }
            lineage: dict[str, object] = {
                "candidate_snapshot_version": snapshot.profile_version,
                "candidate_snapshot_sha256": snapshot.config_sha256,
                "candidate_snapshot_id": str(snapshot.snapshot_id),
                "document_version": new_version,
                "evidence_ids": evidence_ids,
                "manual_revision": True,
                "base_document_id": str(base_document.id),
                "base_version": base_document.version,
                "reason": revision.reason,
                "actor_id": "local-user",
                "provenance": [
                    {
                        "text": claim.text,
                        "evidence_ids": list(claim.evidence_ids),
                        "source_paths": [fact_sources[item] for item in claim.evidence_ids],
                    }
                    for claim in revised_document.claims
                ],
            }
            render_metadata = {
                **revised_render.report.model_dump(mode="json"),
                **lineage,
            }
            report_content = canonical_json_bytes(render_metadata)
            report_path = self._write_exclusive(
                candidate_id,
                application_id,
                f"render_report_{base_document.kind.value}",
                f"v{new_version}.json",
                report_content,
            )
            session.add(
                ApplicationArtifact(
                    candidate_id=candidate_id,
                    application_id=application_id,
                    kind=f"render_report_{base_document.kind.value}",
                    version=new_version,
                    storage_uri=str(report_path),
                    sha256=hashlib.sha256(report_content).hexdigest(),
                    content_type="application/json",
                    immutable=False,
                    artifact_metadata=render_metadata,
                )
            )
            if revised_render.report.valid:
                pdf_path = self._write_exclusive(
                    candidate_id,
                    application_id,
                    f"rendered_{base_document.kind.value}",
                    f"v{new_version}.pdf",
                    revised_render.pdf_bytes,
                )
                session.add(
                    ApplicationArtifact(
                        candidate_id=candidate_id,
                        application_id=application_id,
                        kind=f"rendered_{base_document.kind.value}",
                        version=new_version,
                        storage_uri=str(pdf_path),
                        sha256=revised_render.report.pdf_sha256 or "",
                        content_type="application/pdf",
                        immutable=False,
                        artifact_metadata=render_metadata,
                    )
                )
            session.add(
                AgentReview(
                    candidate_id=candidate_id,
                    application_id=application_id,
                    decision=review.decision,
                    semantic_passed=review.semantic_review_passed,
                    report=review.model_dump(mode="json"),
                )
            )

            previous_state = application.state
            if previous_state is ApplicationState.REVIEW_FAILED:
                self._transition(
                    session,
                    application,
                    ApplicationState.MATERIALS_GENERATING,
                    f"{idempotency_key}:generating",
                    "MANUAL_MATERIAL_REVISION_STARTED",
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
                    "INDEPENDENT_REVIEW_COMPLETED",
                    payload=review.model_dump(mode="json"),
                )
            session.add(
                ApplicationEvent(
                    candidate_id=candidate_id,
                    application_id=application_id,
                    idempotency_key=f"{idempotency_key}:revision",
                    event_type="MATERIAL_MANUALLY_REVISED",
                    from_state=application.state,
                    to_state=application.state,
                    payload={
                        **lineage,
                        "document_id": str(new_document.id),
                        "content_sha256": revised_document.content_sha256,
                        "semantic_review_passed": review.semantic_review_passed,
                    },
                )
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
                "revise_material",
                key_sha256,
                request_sha256,
                view.model_dump(mode="json"),
            )
            return view

    def revise_answer(
        self,
        candidate_id: str,
        application_id: UUID,
        revision: AnswerRevisionRequest,
        idempotency_key: str,
    ) -> ApplicationDetail:
        with self._candidates.lifecycle_write(candidate_id), self._sessions.begin() as session:
            payload = revision.model_dump(mode="json")
            payload["application_id"] = str(application_id)
            replay, request_sha256, key_sha256 = self._administrative_command_replay(
                session, candidate_id, "revise_answer", payload, idempotency_key
            )
            if replay is not None:
                return ApplicationDetail.model_validate(replay)
            application = self._application(session, candidate_id, application_id)
            if application.state not in {
                ApplicationState.REVIEW_PENDING,
                ApplicationState.REVIEW_FAILED,
            }:
                raise ApplicationConflictError(
                    "answers can only be revised while independent review is pending or failed"
                )
            base_answer = session.scalar(
                select(ApplicationAnswer).where(
                    ApplicationAnswer.id == revision.answer_id,
                    ApplicationAnswer.candidate_id == candidate_id,
                    ApplicationAnswer.application_id == application_id,
                )
            )
            if base_answer is None:
                raise ApplicationConflictError("answer revision target was not found")
            latest_by_key = {
                item.question_key: item
                for item in self._latest_answers(
                    session, candidate_id, application_id, include_withdrawn=True
                )
            }
            latest = latest_by_key.get(base_answer.question_key)
            if (
                latest is None
                or latest.id != base_answer.id
                or latest.version != revision.base_version
            ):
                raise ApplicationConflictError("answer revision base version is stale")
            if base_answer.revision_kind in {"withdrawn", "legacy_unknown"}:
                raise ApplicationConflictError(
                    "answer revision requires regenerated snapshot-bound provenance"
                )
            if revision.answer == base_answer.answer:
                raise ApplicationConflictError("answer revision must change the answer text")
            if (
                base_answer.candidate_snapshot_id is None
                or base_answer.candidate_snapshot_version is None
                or base_answer.candidate_snapshot_sha256 is None
            ):
                raise ApplicationConflictError("answer snapshot identity is invalid")
            snapshot_record = session.get(
                CandidateSnapshotRecord, base_answer.candidate_snapshot_id
            )
            if (
                snapshot_record is None
                or snapshot_record.candidate_id != candidate_id
                or snapshot_record.application_id != application_id
                or snapshot_record.profile_version != base_answer.candidate_snapshot_version
                or snapshot_record.sha256 != base_answer.candidate_snapshot_sha256
            ):
                raise ApplicationConflictError("answer snapshot identity is invalid")
            snapshot = self._load_candidate_snapshot(application, snapshot_record)
            try:
                snapshot_config = CandidateConfig.model_validate_json(snapshot.config_json)
            except ValueError as exc:
                raise ApplicationConflictError(
                    "candidate snapshot configuration is invalid"
                ) from exc
            job = session.get(GlobalJob, application.job_id)
            if job is None:
                raise ApplicationConflictError("application job is missing")
            persisted_policy = self._material_policy(application)
            latest_job_version = session.scalar(
                select(JobVersion)
                .where(JobVersion.job_id == job.id)
                .order_by(JobVersion.version.desc())
                .limit(1)
            )
            if (
                latest_job_version is None
                or latest_job_version.version != persisted_policy.job_version
                or latest_job_version.payload_sha256 != persisted_policy.job_payload_sha256
            ):
                raise ApplicationConflictError(
                    "answer revision requires the original unchanged job snapshot"
                )
            generation_request = self._generation_request(snapshot_config, application_id, job)
            if (
                self._build_material_policy(generation_request, snapshot_config, latest_job_version)
                != persisted_policy
            ):
                raise ApplicationConflictError(
                    "answer revision policy no longer matches the reviewed application"
                )

            stored_review = session.scalar(
                select(AgentReview)
                .where(
                    AgentReview.candidate_id == candidate_id,
                    AgentReview.application_id == application_id,
                )
                .order_by(AgentReview.created_at.desc(), AgentReview.id.desc())
                .limit(1)
            )
            if stored_review is None:
                raise ApplicationConflictError("material review is missing")
            try:
                prior_review = MaterialReview.model_validate(stored_review.report)
            except ValueError as exc:
                raise ApplicationConflictError("material review record is invalid") from exc
            if not prior_review.render_reports:
                raise ApplicationConflictError("material review has no rendered document identity")
            canonical_by_kind = {
                document.kind: document
                for document in self._generator.generate(generation_request).documents
            }
            generated_documents: list[GeneratedDocument] = []
            seen_kinds: set[DocumentKind] = set()
            for report in prior_review.render_reports:
                if report.document_kind in seen_kinds:
                    raise ApplicationConflictError(
                        "material review contains duplicate document identity"
                    )
                seen_kinds.add(report.document_kind)
                document = session.scalar(
                    select(ApplicationDocument).where(
                        ApplicationDocument.candidate_id == candidate_id,
                        ApplicationDocument.application_id == application_id,
                        ApplicationDocument.kind == report.document_kind,
                        ApplicationDocument.version == report.document_version,
                    )
                )
                render_report = session.scalar(
                    select(ApplicationArtifact).where(
                        ApplicationArtifact.candidate_id == candidate_id,
                        ApplicationArtifact.application_id == application_id,
                        ApplicationArtifact.kind == f"render_report_{report.document_kind.value}",
                        ApplicationArtifact.version == report.document_version,
                    )
                )
                if (
                    document is None
                    or render_report is None
                    or not self._source_document_valid(document)
                    or not self._render_report_artifact_valid(render_report, document=document)
                    or render_report.artifact_metadata.get("candidate_snapshot_id")
                    != str(snapshot_record.id)
                ):
                    raise ApplicationConflictError(
                        "reviewed document evidence is missing or corrupted"
                    )
                try:
                    stored_report_identity = RenderValidationReport.model_validate(
                        {
                            field: render_report.artifact_metadata[field]
                            for field in RenderValidationReport.model_fields
                        }
                    )
                except (KeyError, ValueError) as exc:
                    raise ApplicationConflictError(
                        "reviewed document report identity is invalid"
                    ) from exc
                if stored_report_identity != report:
                    raise ApplicationConflictError(
                        "reviewed document report identity does not match"
                    )
                canonical = canonical_by_kind.get(document.kind)
                if canonical is None:
                    raise ApplicationConflictError(
                        "reviewed document kind is not enabled by the snapshot"
                    )
                content = Path(document.storage_uri).read_text(encoding="utf-8")
                generated_documents.append(
                    canonical
                    if content == canonical.content
                    else self._manual_document(
                        document.kind,
                        content,
                        generation_request,
                        reject_duplicate_claims=False,
                    )
                )
            if seen_kinds != set(generation_request.requested_documents):
                raise ApplicationConflictError("reviewed document set is incomplete")

            approved = next(
                (
                    item
                    for item in generation_request.approved_answers
                    if item.key == base_answer.question_key and item.answer == revision.answer
                ),
                None,
            )
            new_answer = ApplicationAnswer(
                id=uuid4(),
                candidate_id=candidate_id,
                application_id=application_id,
                question_key=base_answer.question_key,
                question=base_answer.question,
                answer=revision.answer,
                version=base_answer.version + 1,
                sha256=self._answer_sha256(revision.answer),
                actor_id="local-user",
                revision_kind="manual",
                previous_answer_id=base_answer.id,
                reason=revision.reason,
                candidate_snapshot_id=snapshot_record.id,
                candidate_snapshot_version=snapshot_record.profile_version,
                candidate_snapshot_sha256=snapshot_record.sha256,
                approved_source_key=approved.key if approved is not None else None,
                evidence_ids={"items": list(approved.evidence_ids) if approved else []},
                supported=approved is not None,
            )
            current_answers = [
                new_answer if item.question_key == base_answer.question_key else item
                for item in self._latest_answers(session, candidate_id, application_id)
            ]
            generated = GenerationResult(
                candidate_id=candidate_id,
                application_id=application_id,
                target=generation_request.target,
                documents=tuple(generated_documents),
                answers=tuple(self._generated_answer(item) for item in current_answers),
            )
            review = self._reviewer.review(
                generation_request, generated, prior_review.render_reports
            ).model_copy(update={"answer_reports": self._answer_review_identities(current_answers)})
            session.add(new_answer)
            session.add(
                AgentReview(
                    candidate_id=candidate_id,
                    application_id=application_id,
                    decision=review.decision,
                    semantic_passed=review.semantic_review_passed,
                    report=review.model_dump(mode="json"),
                )
            )
            previous_state = application.state
            if previous_state is ApplicationState.REVIEW_FAILED:
                self._transition(
                    session,
                    application,
                    ApplicationState.MATERIALS_GENERATING,
                    f"{idempotency_key}:generating",
                    "MANUAL_ANSWER_REVISION_STARTED",
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
                    "INDEPENDENT_REVIEW_COMPLETED",
                    payload=review.model_dump(mode="json"),
                )
            session.add(
                ApplicationEvent(
                    candidate_id=candidate_id,
                    application_id=application_id,
                    idempotency_key=f"{idempotency_key}:revision",
                    event_type="ANSWER_MANUALLY_REVISED",
                    from_state=application.state,
                    to_state=application.state,
                    payload={
                        "answer_id": str(new_answer.id),
                        "base_answer_id": str(base_answer.id),
                        "question_key": new_answer.question_key,
                        "version": new_answer.version,
                        "sha256": new_answer.sha256,
                        "actor_id": new_answer.actor_id,
                        "reason": new_answer.reason,
                        "supported": new_answer.supported,
                        "semantic_review_passed": review.semantic_review_passed,
                    },
                )
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
                "revise_answer",
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
                .order_by(AgentReview.created_at.desc(), AgentReview.id.desc())
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
        self._candidates.get_config(candidate_id)
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
                .order_by(AgentReview.created_at.desc(), AgentReview.id.desc())
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
            if browser_session.status == "queued":
                raise ApplicationConflictError("a browser dry run is already queued")
            task = self._tasks.enqueue_in_session(
                session,
                candidate_id=candidate_id,
                kind="browser_dry_run",
                idempotency_key=(
                    f"browser:{application_id}:"
                    f"{hashlib.sha256(idempotency_key.encode()).hexdigest()}"
                ),
                payload={
                    "application_id": str(application_id),
                    "session_id": str(browser_session.id),
                    "challenge": command.challenge,
                },
                max_attempts=3,
            )
            browser_session.status = "queued"
            browser_session.stopped_reason = None
            self._append_same_state_event(
                session,
                application,
                f"browser-task:{task.task_id}:queued",
                "BROWSER_DRY_RUN_QUEUED",
                payload={"task_id": str(task.task_id), "challenge": command.challenge},
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

    def execute_browser_task(
        self,
        queue: TaskQueue,
        task: TaskView,
        *,
        worker_id: str,
        executor: BrowserExecutor,
        fixture_base_url: str,
        now: datetime | None = None,
    ) -> TaskView:
        """Execute one leased browser attempt while fenced against candidate erasure."""

        with self._candidates.lifecycle_write(task.candidate_id):
            return self._execute_browser_task_locked(
                queue,
                task,
                worker_id=worker_id,
                executor=executor,
                fixture_base_url=fixture_base_url,
                now=now,
            )

    def _execute_browser_task_locked(
        self,
        queue: TaskQueue,
        task: TaskView,
        *,
        worker_id: str,
        executor: BrowserExecutor,
        fixture_base_url: str,
        now: datetime | None = None,
    ) -> TaskView:
        """Run browser I/O and publish evidence under the held lifecycle fence."""

        started_at = now or datetime.now(UTC)
        try:
            request = self._browser_task_request(task, fixture_base_url)
            result = executor.run(request)
            self._validate_browser_result(task, request, result)
            completed_at = datetime.now(UTC)
            evidence = self._browser_evidence.store(
                task_id=task.task_id,
                attempt=task.attempts,
                result=result,
                started_at=started_at,
                completed_at=completed_at,
            )
        except BrowserWorkerFailure as exc:
            return self._fail_browser_task(
                queue,
                task,
                worker_id=worker_id,
                category=exc.category,
                retryable=exc.retryable,
                safe_message=exc.safe_details,
                now=started_at,
            )
        except (ApplicationConflictError, BrowserEvidenceError, ValueError):
            return self._fail_browser_task(
                queue,
                task,
                worker_id=worker_id,
                category=BrowserFailureCategory.VALIDATION_FAILURE,
                retryable=False,
                safe_message="The browser package or immutable evidence failed validation.",
                now=started_at,
            )
        except Exception:
            return self._fail_browser_task(
                queue,
                task,
                worker_id=worker_id,
                category=BrowserFailureCategory.BROWSER_CRASH,
                retryable=True,
                safe_message="The isolated browser attempt stopped unexpectedly.",
                now=started_at,
            )

        try:
            with self._sessions.begin() as session:
                queue.assert_lease_in_session(
                    session,
                    task.task_id,
                    worker_id=worker_id,
                    expected_attempt=task.attempts,
                )
                self._finalize_browser_task(session, task, result, evidence)
                return queue.complete_in_session(
                    session,
                    task.task_id,
                    worker_id=worker_id,
                    now=completed_at,
                    expected_attempt=task.attempts,
                )
        except TaskLeaseLostError:
            self._browser_evidence.discard(evidence)
            current = queue.get(task.task_id)
            if current is None:
                raise
            return current
        except (ApplicationConflictError, BrowserEvidenceError, ValueError):
            return self._fail_browser_task(
                queue,
                task,
                worker_id=worker_id,
                category=BrowserFailureCategory.VALIDATION_FAILURE,
                retryable=False,
                safe_message="The browser result no longer matches the active application.",
                now=completed_at,
            )

    def _browser_task_request(
        self, task: TaskView, fixture_base_url: str
    ) -> PlaywrightDryRunRequest:
        if task.kind != "browser_dry_run":
            raise ApplicationConflictError("workflow task is not a browser dry run")
        try:
            application_id = UUID(str(task.payload["application_id"]))
            session_id = UUID(str(task.payload["session_id"]))
            challenge_value = task.payload.get("challenge")
        except (KeyError, ValueError) as exc:
            raise ApplicationConflictError("browser task identity is invalid") from exc
        if challenge_value not in {None, "captcha", "otp"}:
            raise ApplicationConflictError("browser task challenge is invalid")
        config = self._candidates.get_config(task.candidate_id)
        with self._sessions() as session:
            application = self._application(session, task.candidate_id, application_id)
            if application.state is not ApplicationState.FORM_FILLING:
                raise ApplicationConflictError("application is not ready for browser execution")
            browser_session = session.get(BrowserSession, session_id)
            if (
                browser_session is None
                or browser_session.candidate_id != task.candidate_id
                or browser_session.application_id != application_id
            ):
                raise ApplicationConflictError("browser task session identity is invalid")
            review = session.scalar(
                select(AgentReview)
                .where(
                    AgentReview.candidate_id == task.candidate_id,
                    AgentReview.application_id == application_id,
                )
                .order_by(AgentReview.created_at.desc(), AgentReview.id.desc())
                .limit(1)
            )
            if review is None:
                raise ApplicationConflictError("reviewed browser package is missing")
            rendered_cv = next(
                (
                    artifact
                    for document, artifact in self._reviewed_materials(session, application, review)
                    if document.kind is DocumentKind.CV
                ),
                None,
            )
            if rendered_cv is None:
                raise ApplicationConflictError("reviewed browser CV is missing")
            fixture_url = f"{fixture_base_url}?challenge={challenge_value or 'none'}"
            name_parts = config.identity.full_name.split()
            return PlaywrightDryRunRequest(
                application_id=application_id,
                candidate_id=task.candidate_id,
                session_id=session_id,
                fixture_url=fixture_url,
                answers={
                    "first_name": name_parts[0],
                    "last_name": name_parts[-1],
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

    def _validate_browser_result(
        self,
        task: TaskView,
        request: PlaywrightDryRunRequest,
        result: PlaywrightDryRunResult,
    ) -> None:
        expected_session = (
            self._runtime_root
            / "candidates"
            / request.candidate_id
            / "sessions"
            / str(request.session_id)
        )
        expected_values: dict[str, str | bool] = {
            **request.answers,
            **{upload.field_key: upload.path.name for upload in request.uploads},
        }
        if (
            task.kind != "browser_dry_run"
            or result.application_id != request.application_id
            or result.candidate_id != request.candidate_id
            or result.session_id != request.session_id
            or result.fixture_url != request.fixture_url
            or result.session_directory.absolute() != expected_session
            or result.persistent_profile_directory.absolute()
            != expected_session / "playwright-profile"
            or result.screenshot_path.absolute() != expected_session / "playwright-final-page.png"
            or result.final_page_snapshot_path.absolute()
            != expected_session / "playwright-final-page.html"
            or result.mapped_values != expected_values
            or result.upload_hashes != tuple(upload.sha256 for upload in request.uploads)
            or result.allowed_network_requests != 1
            or not result.final_submit_present
            or result.ready_for_human_review != (result.human_action is None)
        ):
            raise ApplicationConflictError("browser result failed final-page validation")

    def _finalize_browser_task(
        self,
        session: Session,
        task: TaskView,
        result: PlaywrightDryRunResult,
        evidence: StoredBrowserEvidence,
    ) -> None:
        application_id = UUID(str(task.payload["application_id"]))
        session_id = UUID(str(task.payload["session_id"]))
        if (
            result.candidate_id != task.candidate_id
            or result.application_id != application_id
            or result.session_id != session_id
            or evidence.manifest.task_id != task.task_id
            or evidence.manifest.attempt != task.attempts
        ):
            raise ApplicationConflictError("browser result identity does not match its task")
        application = self._application(session, task.candidate_id, application_id)
        if application.state is not ApplicationState.FORM_FILLING:
            raise ApplicationConflictError("application changed during browser execution")
        browser_session = session.get(BrowserSession, session_id)
        if (
            browser_session is None
            or browser_session.candidate_id != task.candidate_id
            or browser_session.application_id != application_id
        ):
            raise ApplicationConflictError("browser result session identity is invalid")
        manifest_payload = evidence.manifest.model_dump(mode="json")
        event_payload = {
            "task_id": str(task.task_id),
            "attempt": task.attempts,
            "browser_evidence": manifest_payload,
            "final_page": {
                "source_url": result.fixture_url,
                "upload_hashes": list(result.upload_hashes),
                "final_submit_present": result.final_submit_present,
                "final_submit_clicked": False,
            },
        }
        artifact_values = (
            (
                "browser_pre_submit_screenshot",
                evidence.screenshot_path,
                evidence.manifest.screenshot_sha256,
                "image/png",
            ),
            (
                "browser_final_page_snapshot",
                evidence.final_page_path,
                evidence.manifest.final_page_sha256,
                "text/html",
            ),
            (
                "browser_attempt_manifest",
                evidence.manifest_path,
                hashlib.sha256(evidence.manifest_path.read_bytes()).hexdigest(),
                "application/json",
            ),
        )
        for kind, path, digest, content_type in artifact_values:
            version = (
                session.scalar(
                    select(func.max(ApplicationArtifact.version)).where(
                        ApplicationArtifact.candidate_id == task.candidate_id,
                        ApplicationArtifact.application_id == application_id,
                        ApplicationArtifact.kind == kind,
                    )
                )
                or 0
            ) + 1
            session.add(
                ApplicationArtifact(
                    candidate_id=task.candidate_id,
                    application_id=application_id,
                    kind=kind,
                    version=version,
                    storage_uri=str(path),
                    sha256=digest,
                    content_type=content_type,
                    immutable=True,
                    artifact_metadata={
                        "task_id": str(task.task_id),
                        "attempt": task.attempts,
                        "session_id": str(session_id),
                    },
                )
            )
        browser_session.external_session_ref = str(result.session_directory)
        browser_session.stopped_reason = None
        if result.human_action is not None:
            browser_session.status = "human_action_required"
            session.add(
                HumanAction(
                    candidate_id=task.candidate_id,
                    application_id=application_id,
                    actor_id="system",
                    action=HumanActionKind.PAUSE,
                    kind=result.human_action,
                    reason=(
                        f"{result.human_action.upper()} requires human completion in this session."
                    ),
                    payload=event_payload,
                    browser_session_id=session_id,
                    screenshot_uri=str(evidence.screenshot_path),
                    expires_at=datetime.now(UTC) + timedelta(minutes=15),
                )
            )
            self._transition(
                session,
                application,
                ApplicationState.HUMAN_ACTION_REQUIRED,
                f"browser-task:{task.task_id}:attempt:{task.attempts}:human",
                "HUMAN_ACTION_REQUIRED",
                payload=event_payload,
            )
        else:
            browser_session.status = "ready"
            self._transition(
                session,
                application,
                ApplicationState.FINAL_VALIDATION,
                f"browser-task:{task.task_id}:attempt:{task.attempts}:validation",
                "FINAL_VALIDATION_STARTED",
                payload=event_payload,
            )
            self._transition(
                session,
                application,
                ApplicationState.READY_TO_SUBMIT,
                f"browser-task:{task.task_id}:attempt:{task.attempts}:ready",
                "FINAL_VALIDATION_PASSED",
                payload={"synthetic_only": True, "task_id": str(task.task_id)},
            )

    def _fail_browser_task(
        self,
        queue: TaskQueue,
        task: TaskView,
        *,
        worker_id: str,
        category: BrowserFailureCategory,
        retryable: bool,
        safe_message: str,
        now: datetime,
    ) -> TaskView:
        try:
            with (
                self._candidates.lifecycle_write(task.candidate_id),
                self._sessions.begin() as session,
            ):
                failed = queue.fail_in_session(
                    session,
                    task.task_id,
                    worker_id=worker_id,
                    category=category.value,
                    retryable=retryable,
                    safe_details={"message": safe_message},
                    now=now,
                    expected_attempt=task.attempts,
                )
                application_id = UUID(str(task.payload["application_id"]))
                application = self._application(session, task.candidate_id, application_id)
                if application.state is not ApplicationState.FORM_FILLING:
                    return failed
                event_payload = {
                    "task_id": str(task.task_id),
                    "attempt": task.attempts,
                    "category": category.value,
                    "retryable": retryable,
                    "message": safe_message,
                }
                if failed.status == "pending":
                    self._append_same_state_event(
                        session,
                        application,
                        f"browser-task:{task.task_id}:attempt:{task.attempts}:failed",
                        "BROWSER_DRY_RUN_FAILED",
                        payload=event_payload,
                    )
                else:
                    browser_session = session.get(
                        BrowserSession, UUID(str(task.payload["session_id"]))
                    )
                    if browser_session is not None:
                        browser_session.status = "failed"
                        browser_session.stopped_reason = category.value
                    session.add(
                        HumanAction(
                            candidate_id=task.candidate_id,
                            application_id=application_id,
                            actor_id="system",
                            action=HumanActionKind.PAUSE,
                            kind="browser_failure",
                            reason=safe_message,
                            payload=event_payload,
                            browser_session_id=(browser_session.id if browser_session else None),
                            expires_at=now + timedelta(hours=24),
                        )
                    )
                    session.add(
                        NotificationRecord(
                            candidate_id=task.candidate_id,
                            application_id=application_id,
                            event_type="browser_dry_run_failed",
                            channel="dashboard",
                            message="Browser dry run needs human review.",
                            immediate=True,
                        )
                    )
                    self._transition(
                        session,
                        application,
                        ApplicationState.HUMAN_ACTION_REQUIRED,
                        f"browser-task:{task.task_id}:terminal",
                        "BROWSER_DRY_RUN_FAILED",
                        payload=event_payload,
                    )
                return failed
        except TaskLeaseLostError:
            current = queue.get(task.task_id)
            if current is None:
                raise
            return current

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
                    SubmissionAuthorizationRecord.execution_mode == "synthetic",
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
                .order_by(AgentReview.created_at.desc(), AgentReview.id.desc())
                .limit(1)
            )
            reviewed_materials = (
                self._reviewed_materials(session, application, review) if review is not None else ()
            )
            reviewed_documents = tuple(item[0] for item in reviewed_materials)
            rendered_artifacts = tuple(item[1] for item in reviewed_materials)

            answers = self._latest_answers(session, candidate_id, application_id)
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
                cover_letter_valid=not self._cover_letter_included(application)
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
                execution_mode="synthetic",
                authorized_state_version=application.state_version,
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
                or record.execution_mode != "synthetic"
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
                or record.execution_mode != "synthetic"
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
                .order_by(AgentReview.created_at.desc(), AgentReview.id.desc())
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
            submitted_answers = self._archived_submitted_answers(application)
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
                    submitted_answers=submitted_answers,
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
            browser_session: BrowserSession | None = None
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
            resume_browser = (
                not cancel
                and action.kind in {"captcha", "otp"}
                and action.browser_session_id is not None
            )
            if resume_browser:
                assert browser_session is not None
                resume_task = self._tasks.enqueue_in_session(
                    session,
                    candidate_id=candidate_id,
                    kind="browser_dry_run",
                    idempotency_key=f"browser-resume:{action.id}",
                    payload={
                        "application_id": str(application.id),
                        "session_id": str(browser_session.id),
                        "challenge": None,
                    },
                    max_attempts=3,
                )
                browser_session.status = "queued"
                browser_session.stopped_reason = None
                self._transition(
                    session,
                    application,
                    ApplicationState.FORM_FILLING,
                    f"{idempotency_key}:resume",
                    "HUMAN_ACTION_COMPLETED",
                    payload={
                        "action_id": str(action.id),
                        "browser_session_id": str(browser_session.id),
                        "resume_task_id": str(resume_task.task_id),
                    },
                )
            else:
                target = ApplicationState.WITHDRAWN if cancel else ApplicationState.FINAL_VALIDATION
                if not cancel:
                    self._append_same_state_event(
                        session,
                        application,
                        idempotency_key,
                        "HUMAN_ACTION_COMPLETED",
                        payload={"action_id": str(action.id)},
                    )
                self._transition(
                    session,
                    application,
                    target,
                    idempotency_key if cancel else f"{idempotency_key}:validation",
                    "HUMAN_ACTION_CANCELLED" if cancel else "FINAL_VALIDATION_STARTED",
                    payload=None if cancel else action.payload,
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
            return self._settings_view(session, config, record)

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
            view = self._settings_view(session, config, record)
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

    def confirm_autonomy(
        self,
        candidate_id: str,
        request: AutonomyConfirmationRequest,
        idempotency_key: str,
    ) -> SettingsView:
        with self._candidates.lifecycle_write(candidate_id):
            config = self._candidates.get_config(candidate_id)
            payload = request.model_dump(mode="json")
            with self._sessions.begin() as session:
                replay, request_sha256, key_sha256 = self._settings_command_replay(
                    session,
                    candidate_id,
                    "autonomy_confirmation_recorded",
                    payload,
                    idempotency_key,
                )
                if replay is not None:
                    return replay
                record = self._settings_record(session, candidate_id)
                acceptances = tuple(
                    item
                    for item in self._valid_adapter_acceptances(session, candidate_id)
                    if item.adapter in record.allowed_ats_adapters
                )
                dry_run_evidence = self._valid_dry_run_evidence(session, candidate_id)
                provisional = self._settings_view(
                    session,
                    config,
                    record,
                    acceptances=acceptances,
                    ignore_confirmation=True,
                )
                blockers = tuple(
                    blocker
                    for blocker in provisional.autonomy_blockers
                    if blocker != "explicit_confirmation_missing"
                )
                if blockers:
                    raise ApplicationConflictError(
                        "autonomy confirmation prerequisites are blocked: " + ", ".join(blockers)
                    )
                scope_sha256 = self._autonomy_scope_sha256(
                    config, record, acceptances, dry_run_evidence
                )
                confirmed_at = datetime.now(UTC)
                record.explicit_autonomy_confirmation = True
                record.autonomy_confirmation_scope_sha256 = scope_sha256
                record.autonomy_confirmed_at = confirmed_at
                self._append_admin_audit(
                    session,
                    candidate_id,
                    "autonomy_confirmation_recorded",
                    {
                        "consequence_version": request.consequence_version,
                        "scope_sha256": scope_sha256,
                        "tested_adapters": sorted({item.adapter for item in acceptances}),
                        "evidence_ids": [str(item.id) for item in acceptances],
                        "maximum_applications_per_day": record.maximum_applications_per_day,
                        "maximum_applications_per_week": record.maximum_applications_per_week,
                        "maximum_applications_per_company_30_days": (
                            record.maximum_applications_per_company_30_days
                        ),
                    },
                )
                view = self._settings_view(session, config, record, acceptances=acceptances)
                self._append_settings_receipt(
                    session,
                    candidate_id,
                    "autonomy_confirmation_recorded",
                    key_sha256,
                    request_sha256,
                    view,
                )
                return view

    def run_synthetic_adapter_acceptance(
        self,
        candidate_id: str,
        application_id: UUID,
        idempotency_key: str,
    ) -> SettingsView:
        """Exercise the actual controlled adapter in memory and bind it to a passing dry run."""

        with self._candidates.lifecycle_write(candidate_id):
            config = self._candidates.get_config(candidate_id)
            payload = {"application_id": str(application_id), "adapter": "greenhouse"}
            with self._sessions.begin() as session:
                replay, request_sha256, key_sha256 = self._settings_command_replay(
                    session,
                    candidate_id,
                    "synthetic_adapter_acceptance_passed",
                    payload,
                    idempotency_key,
                )
                if replay is not None:
                    return replay
                application = self._application(session, candidate_id, application_id)
                job = session.get(GlobalJob, application.job_id)
                if job is None or (job.ats_platform or "").casefold() != "greenhouse":
                    raise ApplicationConflictError(
                        "synthetic adapter acceptance requires a Greenhouse application"
                    )
                manifest, _screenshot, _final_page = self._verified_browser_evidence(
                    session, application
                )
                if not self._dry_run_manifest_passed(manifest):
                    raise ApplicationConflictError(
                        "synthetic adapter acceptance requires passing browser evidence"
                    )
                review = session.scalar(
                    select(AgentReview)
                    .where(
                        AgentReview.candidate_id == candidate_id,
                        AgentReview.application_id == application_id,
                    )
                    .order_by(AgentReview.created_at.desc(), AgentReview.id.desc())
                    .limit(1)
                )
                if review is None:
                    raise ApplicationConflictError("reviewed adapter package is missing")
                form_payload = self._controlled_form_payload(session, application, review)
                result = SyntheticGreenhouseAcceptanceRunner().run(form_payload)
                manifest_artifact = self._browser_manifest_artifact(session, application, manifest)
                package_sha256 = self._adapter_acceptance_package_sha256(
                    result, manifest, manifest_artifact.sha256
                )
                existing = session.scalar(
                    select(AtsAdapterAcceptanceRecord).where(
                        AtsAdapterAcceptanceRecord.candidate_id == candidate_id,
                        AtsAdapterAcceptanceRecord.adapter == result.adapter,
                        AtsAdapterAcceptanceRecord.adapter_version == result.adapter_version,
                        AtsAdapterAcceptanceRecord.form_fingerprint == result.form_fingerprint,
                        AtsAdapterAcceptanceRecord.browser_task_id == manifest.task_id,
                        AtsAdapterAcceptanceRecord.browser_attempt == manifest.attempt,
                    )
                )
                if existing is None:
                    acceptance = AtsAdapterAcceptanceRecord(
                        candidate_id=candidate_id,
                        application_id=application_id,
                        adapter=result.adapter,
                        adapter_version=result.adapter_version,
                        destination_policy_sha256=result.destination_policy_sha256,
                        form_pattern=result.form_pattern,
                        form_fingerprint=result.form_fingerprint,
                        package_sha256=package_sha256,
                        browser_task_id=manifest.task_id,
                        browser_attempt=manifest.attempt,
                        evidence_manifest_sha256=manifest_artifact.sha256,
                        passed=True,
                        recorded_at=datetime.now(UTC),
                    )
                    session.add(acceptance)
                    session.flush()
                else:
                    acceptance = existing
                    if (
                        not existing.passed
                        or existing.application_id != application_id
                        or existing.destination_policy_sha256 != result.destination_policy_sha256
                        or existing.form_pattern != result.form_pattern
                        or existing.package_sha256 != package_sha256
                        or existing.evidence_manifest_sha256 != manifest_artifact.sha256
                    ):
                        raise ApplicationConflictError(
                            "synthetic adapter acceptance evidence conflicts"
                        )
                self._append_admin_audit(
                    session,
                    candidate_id,
                    "synthetic_adapter_acceptance_passed",
                    {
                        "acceptance_id": str(acceptance.id),
                        "application_id": str(application_id),
                        "adapter": result.adapter,
                        "adapter_version": result.adapter_version,
                        "destination_policy_sha256": result.destination_policy_sha256,
                        "form_fingerprint": result.form_fingerprint,
                        "browser_task_id": str(manifest.task_id),
                        "browser_attempt": manifest.attempt,
                        "evidence_manifest_sha256": manifest_artifact.sha256,
                    },
                )
                view = self._settings_view(
                    session, config, self._settings_record(session, candidate_id)
                )
                self._append_settings_receipt(
                    session,
                    candidate_id,
                    "synthetic_adapter_acceptance_passed",
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
            view = self._settings_view(session, config, record)
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

    @staticmethod
    def _material_terms(*values: str) -> frozenset[str]:
        return frozenset(
            token
            for value in values
            for token in re.findall(r"[a-z0-9+#.]+", value.casefold())
            if len(token) > 1
        )

    @classmethod
    def _experience_relevance(cls, item: ExperienceItem, job: GlobalJob) -> int:
        job_terms = cls._material_terms(
            job.title,
            job.description_normalized or job.description,
            *job.required_skills,
            *job.preferred_skills,
        )
        item_terms = cls._material_terms(
            item.title,
            item.summary or "",
            *item.skills,
            *item.domains,
            *item.role_categories,
        )
        role_bonus = (
            10
            if any(
                cls._material_terms(category) <= cls._material_terms(job.title)
                for category in item.role_categories
            )
            else 0
        )
        return len(job_terms & item_terms) + role_bonus

    @classmethod
    def _project_relevance(cls, item: ProjectItem, job: GlobalJob) -> int:
        job_terms = cls._material_terms(
            job.title,
            job.description_normalized or job.description,
            *job.required_skills,
            *job.preferred_skills,
        )
        item_terms = cls._material_terms(
            item.name,
            item.description,
            *item.skills,
            *item.domains,
            *item.role_categories,
        )
        role_bonus = (
            10
            if any(
                cls._material_terms(category) <= cls._material_terms(job.title)
                for category in item.role_categories
            )
            else 0
        )
        return len(job_terms & item_terms) + role_bonus

    @classmethod
    def _cover_letter_decision(
        cls, config: CandidateConfig, job: GlobalJob
    ) -> tuple[bool, str | None]:
        rules = config.cover_letter_rules
        if not rules.enabled or rules.generation_mode == "never":
            return False, None
        if job.raw_payload.get("cover_letter_required") is True:
            return True, "source_required"
        if job.raw_payload.get("cover_letter_recommended") is True:
            return True, "source_recommended"
        if rules.generation_mode == "always":
            return True, "candidate_requested"
        if rules.generation_mode == "priority_only":
            if job.company.casefold() in {item.casefold() for item in config.companies.target}:
                return True, "priority_company"
            highest_priority_tier = min(
                (tier.tier for tier in config.career_strategy.role_tiers), default=None
            )
            high_priority_roles = {
                role.casefold()
                for tier in config.career_strategy.role_tiers
                if tier.tier == highest_priority_tier
                for role in tier.roles
            }
            if job.title.casefold() in high_priority_roles:
                return True, "priority_role"
        for motivation in rules.motivations:
            if not motivation.approved or not (motivation.companies or motivation.roles):
                continue
            company_match = not motivation.companies or job.company.casefold() in {
                value.casefold() for value in motivation.companies
            }
            role_match = not motivation.roles or job.title.casefold() in {
                value.casefold() for value in motivation.roles
            }
            if company_match and role_match:
                return True, f"approved_motivation:{motivation.motivation_id}"
        return False, None

    @classmethod
    def _cv_template(cls, config: CandidateConfig, job: GlobalJob) -> str:
        job_terms = cls._material_terms(job.title)
        matches = [
            (len(cls._material_terms(role)), role, template)
            for role, template in config.cv_rules.template_by_role.items()
            if cls._material_terms(role) and cls._material_terms(role) <= job_terms
        ]
        if not matches:
            return config.cv_rules.template_id
        return sorted(matches, key=lambda item: (-item[0], item[1].casefold()))[0][2]

    @staticmethod
    def _build_material_policy(
        request: GenerationRequest,
        config: CandidateConfig,
        job_version: JobVersion,
    ) -> ApplicationMaterialPolicy:
        included = DocumentKind.COVER_LETTER in request.requested_documents
        return ApplicationMaterialPolicy(
            generator_version="deterministic_material_v2",
            job_version=job_version.version,
            job_payload_sha256=job_version.payload_sha256,
            cv_template_id=request.cv_template_id,
            cv_template_version=config.cv_rules.template_version,
            selected_experience_ids=request.selected_experience_ids,
            selected_project_ids=request.selected_project_ids,
            cover_letter={
                "included": included,
                "reason": request.cover_letter_reason,
                "selected_experience_ids": request.cover_letter_experience_ids,
                "selected_project_ids": request.cover_letter_project_ids,
                "minimum_words": request.cover_letter_min_words,
                "maximum_words": request.cover_letter_max_words,
            },
        )

    def _generation_request(
        self, config: CandidateConfig, application_id: UUID, job: GlobalJob
    ) -> GenerationRequest:
        eligible_experiences = tuple(
            item
            for item in config.experience.items
            if item.approved
            and not item.archived
            and item.confidentiality == "public"
            and (item.cv_eligible or item.cover_letter_eligible)
        )
        ranked_experiences = tuple(
            sorted(
                eligible_experiences,
                key=lambda item: (-self._experience_relevance(item, job), item.id),
            )
        )
        eligible_projects = tuple(
            item
            for item in config.projects.items
            if item.approved
            and not item.archived
            and item.confidentiality != "internal"
            and (item.cv_eligible or item.cover_letter_eligible)
        )
        ranked_projects = tuple(
            sorted(
                eligible_projects,
                key=lambda item: (-self._project_relevance(item, job), item.id),
            )
        )
        cover_letter_included, cover_letter_reason = self._cover_letter_decision(config, job)
        cv_experience_ids = {
            item.id
            for item in tuple(item for item in ranked_experiences if item.cv_eligible)[
                : config.cv_rules.max_experiences
            ]
        }
        cover_experience_ids = (
            {
                item.id
                for item in tuple(
                    item for item in ranked_experiences if item.cover_letter_eligible
                )[: config.cover_letter_rules.max_experiences]
            }
            if cover_letter_included
            else set()
        )
        cv_project_ids = {
            item.id
            for item in tuple(item for item in ranked_projects if item.cv_eligible)[
                : config.cv_rules.max_projects
            ]
        }
        cover_project_ids = (
            {
                item.id
                for item in tuple(item for item in ranked_projects if item.cover_letter_eligible)[
                    : config.cover_letter_rules.max_projects
                ]
            }
            if cover_letter_included
            else set()
        )
        facts: list[ApprovedFact] = []
        if config.biography.approved:
            facts.append(
                ApprovedFact(
                    fact_id="biography_summary",
                    text=config.biography.summary,
                    source_path="biography.summary",
                    document_kinds=(
                        (DocumentKind.CV, DocumentKind.COVER_LETTER)
                        if cover_letter_included
                        else (DocumentKind.CV,)
                    ),
                )
            )
        for experience in config.experience.items:
            if experience.id not in cv_experience_ids | cover_experience_ids:
                continue
            document_kinds = tuple(
                kind
                for kind, eligible in (
                    (DocumentKind.CV, experience.id in cv_experience_ids),
                    (
                        DocumentKind.COVER_LETTER,
                        cover_letter_included and experience.id in cover_experience_ids,
                    ),
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
            if project.id not in cv_project_ids | cover_project_ids:
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
                    (DocumentKind.CV, project.id in cv_project_ids),
                    (
                        DocumentKind.COVER_LETTER,
                        cover_letter_included and project.id in cover_project_ids,
                    ),
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
        if cover_letter_included:
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
            cv_template_id=self._cv_template(config, job),
            selected_experience_ids=tuple(
                item.id for item in ranked_experiences if item.id in cv_experience_ids
            ),
            selected_project_ids=tuple(
                item.id for item in ranked_projects if item.id in cv_project_ids
            ),
            cover_letter_experience_ids=tuple(
                item.id for item in ranked_experiences if item.id in cover_experience_ids
            ),
            cover_letter_project_ids=tuple(
                item.id for item in ranked_projects if item.id in cover_project_ids
            ),
            cover_letter_reason=cover_letter_reason,
            cover_letter_min_words=config.cover_letter_rules.min_words,
            cover_letter_max_words=config.cover_letter_rules.max_words,
        )

    def _manual_document(
        self,
        kind: DocumentKind,
        content: str,
        request: GenerationRequest,
        *,
        reject_duplicate_claims: bool,
    ) -> GeneratedDocument:
        heading = (
            f"CV — {request.target.title} at {request.target.company}"
            if kind is DocumentKind.CV
            else f"Application for {request.target.title} at {request.target.company}"
        )
        paragraphs = content.split("\n\n")
        if not paragraphs or paragraphs[0] != heading or "\r" in content:
            raise ApplicationConflictError(
                "manual material must preserve the canonical job heading"
            )
        if kind is DocumentKind.COVER_LETTER:
            return self._manual_cover_letter(
                content,
                request,
                reject_duplicate_claims=reject_duplicate_claims,
            )
        approved_by_text: dict[str, list[str]] = {}
        for fact in request.approved_facts:
            if kind in fact.document_kinds:
                approved_by_text.setdefault(fact.text, []).append(fact.fact_id)
        claims: list[Claim] = []
        seen: set[str] = set()
        for paragraph in paragraphs[1:]:
            if not paragraph.startswith("- ") or "\n" in paragraph:
                raise ApplicationConflictError(
                    "manual material may contain only canonical approved-fact bullets"
                )
            text = paragraph[2:]
            evidence_ids = approved_by_text.get(text)
            if not text or evidence_ids is None:
                raise ApplicationConflictError(
                    "manual material contains a claim not present in the approved snapshot"
                )
            if reject_duplicate_claims and text in seen:
                raise ApplicationConflictError("manual material contains a duplicate claim")
            seen.add(text)
            claims.append(Claim(text=text, evidence_ids=tuple(sorted(evidence_ids))))
        if not claims:
            raise ApplicationConflictError("manual material must retain at least one approved fact")
        canonical = "\n\n".join((heading, *(f"- {claim.text}" for claim in claims)))
        if canonical != content:
            raise ApplicationConflictError("manual material formatting is not canonical")
        return GeneratedDocument(
            kind=kind,
            company=request.target.company,
            content=content,
            claims=tuple(claims),
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            minimum_words=None,
            maximum_words=None,
        )

    def _manual_cover_letter(
        self,
        content: str,
        request: GenerationRequest,
        *,
        reject_duplicate_claims: bool,
    ) -> GeneratedDocument:
        canonical = next(
            document
            for document in self._generator.generate(request).documents
            if document.kind is DocumentKind.COVER_LETTER
        )
        canonical_claims = {f"{claim.text}.": claim for claim in canonical.claims}
        canonical_static = tuple(
            paragraph
            for paragraph in canonical.content.split("\n\n")
            if paragraph not in canonical_claims
        )
        paragraphs = tuple(content.split("\n\n"))
        supplied_static = tuple(
            paragraph for paragraph in paragraphs if paragraph not in canonical_claims
        )
        if supplied_static != canonical_static:
            raise ApplicationConflictError(
                "manual cover letter must preserve canonical evidence-safe prose"
            )
        claims: list[Claim] = []
        seen: set[str] = set()
        for paragraph in paragraphs:
            claim = canonical_claims.get(paragraph)
            if claim is None:
                continue
            if reject_duplicate_claims and claim.text in seen:
                raise ApplicationConflictError("manual material contains a duplicate claim")
            seen.add(claim.text)
            claims.append(claim)
        if not claims:
            raise ApplicationConflictError("manual material must retain at least one approved fact")
        canonical_content = "\n\n".join(paragraphs)
        if canonical_content != content:
            raise ApplicationConflictError("manual material formatting is not canonical")
        return GeneratedDocument(
            kind=DocumentKind.COVER_LETTER,
            company=request.target.company,
            content=content,
            claims=tuple(claims),
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            minimum_words=request.cover_letter_min_words,
            maximum_words=request.cover_letter_max_words,
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

    def _render_report_artifact_valid(
        self,
        artifact: ApplicationArtifact,
        *,
        document: ApplicationDocument,
    ) -> bool:
        if (
            artifact.content_type != "application/json"
            or artifact.artifact_metadata.get("source_sha256") != document.sha256
            or artifact.artifact_metadata.get("document_version") != document.version
            or artifact.candidate_id != document.candidate_id
            or artifact.application_id != document.application_id
            or artifact.version != document.version
            or artifact.kind != f"render_report_{document.kind.value}"
        ):
            return False
        try:
            application_root = self._candidate_application_root(
                artifact.candidate_id, artifact.application_id, create=False
            )
        except ApplicationConflictError:
            return False
        path = Path(artifact.storage_uri).absolute()
        expected = application_root / artifact.kind / f"v{artifact.version}.json"
        if path != expected or path.is_symlink() or path.parent.is_symlink() or not path.is_file():
            return False
        content = path.read_bytes()
        return hashlib.sha256(
            content
        ).hexdigest() == artifact.sha256 and content == canonical_json_bytes(
            artifact.artifact_metadata
        )

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

    @staticmethod
    def _answer_sha256(answer: str) -> str:
        return hashlib.sha256(answer.encode("utf-8")).hexdigest()

    @staticmethod
    def _generated_answer(answer: ApplicationAnswer) -> GeneratedAnswer:
        return GeneratedAnswer(
            question_key=answer.question_key,
            question=answer.question,
            answer=answer.answer,
            approved_source_key=answer.approved_source_key,
            evidence_ids=tuple(answer.evidence_ids.get("items", [])),
            supported=answer.supported,
        )

    @staticmethod
    def _answer_review_identities(
        answers: Sequence[ApplicationAnswer],
    ) -> tuple[AnswerReviewIdentity, ...]:
        identities: list[AnswerReviewIdentity] = []
        for answer in sorted(answers, key=lambda item: item.question_key):
            if (
                answer.revision_kind in {"withdrawn", "legacy_unknown"}
                or answer.candidate_snapshot_id is None
                or answer.sha256 != hashlib.sha256(answer.answer.encode("utf-8")).hexdigest()
            ):
                raise ApplicationConflictError("answer revision provenance is invalid")
            identities.append(
                AnswerReviewIdentity(
                    answer_id=answer.id,
                    question_key=answer.question_key,
                    version=answer.version,
                    sha256=answer.sha256,
                    candidate_snapshot_id=answer.candidate_snapshot_id,
                )
            )
        return tuple(identities)

    @staticmethod
    def _latest_answers(
        session: Session,
        candidate_id: str,
        application_id: UUID,
        *,
        include_withdrawn: bool = False,
    ) -> list[ApplicationAnswer]:
        latest = (
            select(
                ApplicationAnswer.candidate_id.label("candidate_id"),
                ApplicationAnswer.application_id.label("application_id"),
                ApplicationAnswer.question_key.label("question_key"),
                func.max(ApplicationAnswer.version).label("version"),
            )
            .where(
                ApplicationAnswer.candidate_id == candidate_id,
                ApplicationAnswer.application_id == application_id,
            )
            .group_by(
                ApplicationAnswer.candidate_id,
                ApplicationAnswer.application_id,
                ApplicationAnswer.question_key,
            )
            .subquery()
        )
        statement = (
            select(ApplicationAnswer)
            .join(
                latest,
                (ApplicationAnswer.candidate_id == latest.c.candidate_id)
                & (ApplicationAnswer.application_id == latest.c.application_id)
                & (ApplicationAnswer.question_key == latest.c.question_key)
                & (ApplicationAnswer.version == latest.c.version),
            )
            .order_by(ApplicationAnswer.question_key)
        )
        if not include_withdrawn:
            statement = statement.where(ApplicationAnswer.revision_kind != "withdrawn")
        return list(session.scalars(statement).all())

    def _validate_reviewed_answers(
        self, session: Session, application: Application, material_review: MaterialReview
    ) -> tuple[ApplicationAnswer, ...]:
        answers = tuple(self._latest_answers(session, application.candidate_id, application.id))
        reports = {report.question_key: report for report in material_review.answer_reports}
        if len(reports) != len(material_review.answer_reports) or len(reports) != len(answers):
            raise ApplicationConflictError("material review answer identity is incomplete")
        snapshot_configs: dict[UUID, CandidateConfig] = {}
        for answer in answers:
            report = reports.get(answer.question_key)
            snapshot = (
                session.get(CandidateSnapshotRecord, answer.candidate_snapshot_id)
                if answer.candidate_snapshot_id is not None
                else None
            )
            snapshot_config: CandidateConfig | None = None
            if snapshot is not None:
                snapshot_config = snapshot_configs.get(snapshot.id)
                if snapshot_config is None:
                    loaded_snapshot = self._load_candidate_snapshot(application, snapshot)
                    try:
                        snapshot_config = CandidateConfig.model_validate_json(
                            loaded_snapshot.config_json
                        )
                    except ValueError as exc:
                        raise ApplicationConflictError(
                            "reviewed answer snapshot configuration is invalid"
                        ) from exc
                    snapshot_configs[snapshot.id] = snapshot_config
            approved_answer = (
                next(
                    (
                        item
                        for item in snapshot_config.approved_answers.items
                        if item.key == answer.question_key
                    ),
                    None,
                )
                if snapshot_config is not None
                else None
            )
            today = date.today()
            if (
                report is None
                or report.answer_id != answer.id
                or report.version != answer.version
                or report.sha256 != answer.sha256
                or report.candidate_snapshot_id != answer.candidate_snapshot_id
                or answer.sha256 != self._answer_sha256(answer.answer)
                or answer.revision_kind in {"withdrawn", "legacy_unknown"}
                or not answer.supported
                or answer.approved_source_key is None
                or snapshot is None
                or snapshot.candidate_id != application.candidate_id
                or snapshot.application_id != application.id
                or snapshot.profile_version != answer.candidate_snapshot_version
                or snapshot.sha256 != answer.candidate_snapshot_sha256
                or approved_answer is None
                or not approved_answer.approved
                or not approved_answer.auto_submit_allowed
                or approved_answer.archived
                or (approved_answer.valid_from is not None and approved_answer.valid_from > today)
                or (approved_answer.valid_until is not None and approved_answer.valid_until < today)
                or approved_answer.question_pattern != answer.question
                or approved_answer.answer != answer.answer
                or approved_answer.key != answer.approved_source_key
                or tuple(approved_answer.evidence_ids)
                != tuple(answer.evidence_ids.get("items", []))
            ):
                raise ApplicationConflictError("reviewed answer identity is invalid")
        return answers

    def _reviewed_materials(
        self, session: Session, application: Application, review: AgentReview
    ) -> tuple[tuple[ApplicationDocument, ApplicationArtifact], ...]:
        try:
            material_review = MaterialReview.model_validate(review.report)
        except ValueError as exc:
            raise ApplicationConflictError("material review record is invalid") from exc
        if not review.semantic_passed or not material_review.semantic_review_passed:
            raise ApplicationConflictError("materials did not pass independent review")
        self._validate_reviewed_answers(session, application, material_review)
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

    def _browser_upload_hashes(self, session: Session, application: Application) -> tuple[str, ...]:
        try:
            manifest, _screenshot, _final_page = self._verified_browser_evidence(
                session, application
            )
        except ApplicationConflictError:
            return ()
        return manifest.upload_hashes

    def _verified_browser_evidence(
        self, session: Session, application: Application
    ) -> tuple[BrowserAttemptManifest, bytes, bytes]:
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
            raise ApplicationConflictError("verified browser evidence is missing")
        try:
            manifest = BrowserAttemptManifest.model_validate(event.payload["browser_evidence"])
        except (KeyError, ValueError) as exc:
            raise ApplicationConflictError("verified browser evidence identity is invalid") from exc
        if (
            manifest.candidate_id != application.candidate_id
            or manifest.application_id != application.id
        ):
            raise ApplicationConflictError("verified browser evidence identity is invalid")
        artifacts = session.scalars(
            select(ApplicationArtifact).where(
                ApplicationArtifact.candidate_id == application.candidate_id,
                ApplicationArtifact.application_id == application.id,
                ApplicationArtifact.kind.in_(
                    {
                        "browser_pre_submit_screenshot",
                        "browser_final_page_snapshot",
                        "browser_attempt_manifest",
                    }
                ),
            )
        ).all()
        matching_artifacts = [
            artifact
            for artifact in artifacts
            if artifact.artifact_metadata.get("task_id") == str(manifest.task_id)
            and artifact.artifact_metadata.get("attempt") == manifest.attempt
            and artifact.artifact_metadata.get("session_id") == str(manifest.session_id)
        ]
        by_kind = {artifact.kind: artifact for artifact in matching_artifacts}
        if (
            set(by_kind)
            != {
                "browser_pre_submit_screenshot",
                "browser_final_page_snapshot",
                "browser_attempt_manifest",
            }
            or len(matching_artifacts) != 3
        ):
            raise ApplicationConflictError("verified browser evidence artifacts are incomplete")
        content: dict[str, bytes] = {}
        expected_directory = (
            self._runtime_root
            / "candidates"
            / application.candidate_id
            / "browser_evidence"
            / str(manifest.task_id)
            / f"attempt-{manifest.attempt}"
        )
        for kind, artifact in by_kind.items():
            raw_path = Path(artifact.storage_uri).absolute()
            if not raw_path.is_relative_to(self._runtime_root):
                raise ApplicationConflictError("verified browser evidence path is invalid")
            for parent in (raw_path, *raw_path.parents):
                if parent == self._runtime_root:
                    break
                if parent.is_symlink():
                    raise ApplicationConflictError("verified browser evidence path is invalid")
            try:
                resolved = raw_path.resolve(strict=True)
            except OSError as exc:
                raise ApplicationConflictError("verified browser evidence is missing") from exc
            if (
                raw_path.is_symlink()
                or resolved.parent != expected_directory.resolve()
                or artifact.artifact_metadata.get("task_id") != str(manifest.task_id)
                or artifact.artifact_metadata.get("attempt") != manifest.attempt
                or artifact.artifact_metadata.get("session_id") != str(manifest.session_id)
            ):
                raise ApplicationConflictError("verified browser evidence path is invalid")
            value = resolved.read_bytes()
            if hashlib.sha256(value).hexdigest() != artifact.sha256:
                raise ApplicationConflictError("verified browser evidence hash does not match")
            content[kind] = value
        try:
            stored_manifest = BrowserAttemptManifest.model_validate_json(
                content["browser_attempt_manifest"]
            )
        except ValueError as exc:
            raise ApplicationConflictError("verified browser evidence manifest is invalid") from exc
        if (
            stored_manifest != manifest
            or hashlib.sha256(content["browser_pre_submit_screenshot"]).hexdigest()
            != manifest.screenshot_sha256
            or hashlib.sha256(content["browser_final_page_snapshot"]).hexdigest()
            != manifest.final_page_sha256
        ):
            raise ApplicationConflictError("verified browser evidence manifest does not match")
        return (
            manifest,
            content["browser_pre_submit_screenshot"],
            content["browser_final_page_snapshot"],
        )

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

    def _archived_submitted_answers(self, application: Application) -> tuple[SubmittedAnswer, ...]:
        if application.archive_uri is None:
            raise ApplicationConflictError("submitted answer archive is missing")
        archive_path = self._safe_archive_path(application.archive_uri)
        if archive_path is None or not self._archives.verify(archive_path):
            raise ApplicationConflictError("submitted answer archive is invalid")
        try:
            raw_answers = json.loads(
                (archive_path / "answers" / "final_answers.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise ApplicationConflictError("submitted answer archive is invalid") from exc
        if not isinstance(raw_answers, list):
            raise ApplicationConflictError("submitted answer archive is invalid")
        answers: list[SubmittedAnswer] = []
        seen_keys: set[str] = set()
        for raw in raw_answers:
            if not isinstance(raw, dict):
                raise ApplicationConflictError("submitted answer archive is invalid")
            question_key = raw.get("question_key")
            question = raw.get("question")
            answer = raw.get("answer")
            sha256 = raw.get("sha256")
            version = raw.get("version")
            if (
                not isinstance(question_key, str)
                or not question_key
                or question_key in seen_keys
                or not isinstance(question, str)
                or not question
                or not isinstance(answer, str)
                or not answer
                or not isinstance(version, int)
                or version < 1
                or not isinstance(sha256, str)
                or not hmac.compare_digest(sha256, self._answer_sha256(answer))
            ):
                raise ApplicationConflictError("submitted answer archive is invalid")
            seen_keys.add(question_key)
            answers.append(SubmittedAnswer(question=question, answer=answer))
        if not answers:
            raise ApplicationConflictError("submitted answer archive is incomplete")
        return tuple(answers)

    @classmethod
    def _raw_job_html(cls, payload: object) -> bytes | None:
        """Return only exact HTML found in provider evidence; never synthesize source capture."""
        if isinstance(payload, dict):
            for key in ("content", "descriptionHtml", "description_html", "description"):
                value = payload.get(key)
                if isinstance(value, str) and "<" in value and ">" in value:
                    return value.encode("utf-8")
            for value in payload.values():
                found = cls._raw_job_html(value)
                if found is not None:
                    return found
        elif isinstance(payload, list):
            for value in payload:
                found = cls._raw_job_html(value)
                if found is not None:
                    return found
        return None

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
            .order_by(AgentReview.created_at.desc(), AgentReview.id.desc())
            .limit(1)
        )
        if review is None:
            raise ApplicationConflictError("material review is missing")
        job_version = (
            session.scalar(
                select(JobVersion)
                .where(JobVersion.job_id == job.id)
                .order_by(JobVersion.version.desc())
                .limit(1)
            )
            if job is not None
            else None
        )
        analysis_provenance = (
            score.rationale.get("agent_analysis", {})
            if score is not None and isinstance(score.rationale, dict)
            else {}
        )
        reviewed_materials = self._reviewed_materials(session, application, review)
        reviewed_documents = tuple(item[0] for item in reviewed_materials)
        rendered_artifacts = tuple(item[1] for item in reviewed_materials)
        snapshot_id = UUID(str(rendered_artifacts[0].artifact_metadata["candidate_snapshot_id"]))
        snapshot_record = session.get(CandidateSnapshotRecord, snapshot_id)
        if snapshot_record is None:
            raise ApplicationConflictError("candidate snapshot is missing")
        candidate_snapshot = self._load_candidate_snapshot(application, snapshot_record)
        _browser_manifest, browser_screenshot, browser_final_page = self._verified_browser_evidence(
            session, application
        )

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
                        "answer_id": str(item.id),
                        "question": item.question,
                        "question_key": item.question_key,
                        "answer": item.answer,
                        "version": item.version,
                        "sha256": item.sha256,
                        "revision_kind": item.revision_kind,
                        "actor_id": item.actor_id,
                        "previous_answer_id": (
                            str(item.previous_answer_id) if item.previous_answer_id else None
                        ),
                        "reason": item.reason,
                        "approved_source_key": item.approved_source_key,
                        "evidence_ids": item.evidence_ids.get("items", []),
                        "candidate_snapshot_id": (
                            str(item.candidate_snapshot_id) if item.candidate_snapshot_id else None
                        ),
                        "candidate_snapshot_version": item.candidate_snapshot_version,
                        "candidate_snapshot_sha256": item.candidate_snapshot_sha256,
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
                    ("cv", "cover_letter") if self._cover_letter_included(application) else ("cv",)
                ),
                job_post_raw_html=(
                    self._raw_job_html(job_version.source_payload)
                    if job_version is not None
                    else None
                ),
                browser_pre_submit_screenshot=browser_screenshot,
                browser_final_page_snapshot=browser_final_page,
                agent_version=(
                    "career-os-agent-contracts-v1;"
                    f"document_generation:{self._generator_provenance.agent_version};"
                    f"independent_review:{self._reviewer_provenance.agent_version}"
                ),
                model_versions={
                    "job_analysis": str(
                        analysis_provenance.get("model") or "deterministic-scoring-v1"
                    ),
                    "document_generation": self._generator_provenance.model_version,
                    "independent_review": self._reviewer_provenance.model_version,
                },
                prompt_versions={
                    "job_analysis": str(analysis_provenance.get("prompt_version") or "1.0"),
                    "document_generation": self._generator_provenance.prompt_version,
                    "independent_review": self._reviewer_provenance.prompt_version,
                },
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

    @staticmethod
    def _append_same_state_event(
        session: Session,
        application: Application,
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
            if existing.event_type != event_type or existing.payload != (payload or {}):
                raise ApplicationConflictError("idempotency key was reused for another event")
            return
        session.add(
            ApplicationEvent(
                candidate_id=application.candidate_id,
                application_id=application.id,
                idempotency_key=idempotency_key,
                event_type=event_type,
                from_state=application.state,
                to_state=application.state,
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
        browser_status = None
        if application.state is ApplicationState.FORM_FILLING:
            browser_status = session.scalar(
                select(BrowserSession.status)
                .where(
                    BrowserSession.candidate_id == application.candidate_id,
                    BrowserSession.application_id == application.id,
                )
                .order_by(BrowserSession.created_at.desc())
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
            next_action=(
                "Waiting for isolated browser worker"
                if browser_status == "queued"
                else self._next_action(application.state)
            ),
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
            select(ApplicationAnswer)
            .where(
                ApplicationAnswer.candidate_id == application.candidate_id,
                ApplicationAnswer.application_id == application.id,
            )
            .order_by(ApplicationAnswer.question_key, ApplicationAnswer.version)
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
            .order_by(AgentReview.created_at.desc(), AgentReview.id.desc())
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
        artifacts = session.scalars(
            select(ApplicationArtifact).where(
                ApplicationArtifact.candidate_id == application.candidate_id,
                ApplicationArtifact.application_id == application.id,
            )
        ).all()
        report_metadata = {
            (item.kind.removeprefix("render_report_"), item.version): item.artifact_metadata
            for item in artifacts
            if item.kind.startswith("render_report_")
        }
        latest_versions = {
            kind: max(item.version for item in documents if item.kind is kind)
            for kind in {item.kind for item in documents}
        }
        if any(not self._source_document_valid(item) for item in documents):
            raise ApplicationConflictError("application source document is missing or corrupted")

        def document_view(item: ApplicationDocument) -> DocumentView:
            metadata = report_metadata.get((item.kind.value, item.version), {})
            raw_base_id = metadata.get("base_document_id")
            try:
                base_id = UUID(str(raw_base_id)) if raw_base_id is not None else None
            except ValueError:
                base_id = None
            raw_provenance = metadata.get("provenance", [])
            provenance = (
                tuple(entry for entry in raw_provenance if isinstance(entry, dict))
                if isinstance(raw_provenance, list)
                else ()
            )
            editable_state = application.state in {
                ApplicationState.REVIEW_PENDING,
                ApplicationState.REVIEW_FAILED,
            }
            return DocumentView(
                document_id=item.id,
                kind=item.kind.value,
                version=item.version,
                content=Path(item.storage_uri).read_text(encoding="utf-8"),
                sha256=item.sha256,
                immutable=not editable_state or item.version != latest_versions[item.kind],
                validated=item.validated,
                evidence_ids=tuple(item.evidence_ids.get("items", [])),
                created_at=item.created_at,
                provenance=provenance,
                revision_actor=(
                    str(metadata["actor_id"]) if metadata.get("actor_id") is not None else None
                ),
                base_document_id=base_id,
                render_metadata=metadata,
            )

        return ApplicationDetail(
            **summary.model_dump(),
            source_url=job.url if job else "",
            ats_platform=job.ats_platform if job else None,
            documents=tuple(document_view(item) for item in documents),
            answers=tuple(
                AnswerView(
                    answer_id=item.id,
                    question_key=item.question_key,
                    question=item.question,
                    answer=item.answer,
                    version=item.version,
                    sha256=item.sha256,
                    immutable=(
                        item.revision_kind in {"withdrawn", "legacy_unknown"}
                        or application.state
                        not in {ApplicationState.REVIEW_PENDING, ApplicationState.REVIEW_FAILED}
                        or item.version
                        != max(
                            answer.version
                            for answer in answers
                            if answer.question_key == item.question_key
                        )
                    ),
                    revision_kind=item.revision_kind,
                    revision_actor=item.actor_id,
                    base_answer_id=item.previous_answer_id,
                    reason=item.reason,
                    approved_source_key=item.approved_source_key,
                    candidate_snapshot_id=item.candidate_snapshot_id,
                    candidate_snapshot_version=item.candidate_snapshot_version,
                    candidate_snapshot_sha256=item.candidate_snapshot_sha256,
                    supported=item.supported,
                    evidence_ids=tuple(item.evidence_ids.get("items", [])),
                    created_at=item.created_at,
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
            material_policy=self._material_policy_view(application),
        )

    @staticmethod
    def _next_action(state: ApplicationState) -> str:
        return {
            ApplicationState.REVIEW_PENDING: "Approve materials",
            ApplicationState.REVIEW_FAILED: "Revise or regenerate materials",
            ApplicationState.APPLICATION_STARTED: "Start synthetic dry run",
            ApplicationState.FORM_FILLING: "Complete dry run",
            ApplicationState.HUMAN_ACTION_REQUIRED: "Complete human action",
            ApplicationState.READY_TO_SUBMIT: "Authorize synthetic submission",
            ApplicationState.FAILED_RETRYABLE: "Inspect and retry",
            ApplicationState.UNKNOWN_AFTER_CLICK: "Do not retry; inspect submission outcome",
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

    def _human_action_view(self, session: Session, action: HumanAction) -> HumanActionView:
        application = session.get(Application, action.application_id)
        job = session.get(GlobalJob, application.job_id) if application else None
        browser_session = (
            session.get(BrowserSession, action.browser_session_id)
            if action.browser_session_id is not None
            else None
        )
        expected_task_id = action.payload.get("task_id")
        expected_attempt = action.payload.get("attempt")
        screenshot = next(
            (
                item
                for item in session.scalars(
                    select(ApplicationArtifact)
                    .where(
                        ApplicationArtifact.candidate_id == action.candidate_id,
                        ApplicationArtifact.application_id == action.application_id,
                        ApplicationArtifact.kind == "browser_pre_submit_screenshot",
                        ApplicationArtifact.immutable.is_(True),
                    )
                    .order_by(ApplicationArtifact.version.desc())
                ).all()
                if (
                    str(item.artifact_metadata.get("session_id")) == str(action.browser_session_id)
                    and item.artifact_metadata.get("task_id") == expected_task_id
                    and item.artifact_metadata.get("attempt") == expected_attempt
                )
            ),
            None,
        )
        if screenshot is not None:
            raw_screenshot_path = Path(screenshot.storage_uri).absolute()
            expected_screenshot_directory = (
                self._runtime_root
                / "candidates"
                / action.candidate_id
                / "browser_evidence"
                / str(expected_task_id)
                / f"attempt-{expected_attempt}"
            )
            screenshot_parent_symlinked = any(
                parent.is_symlink()
                for parent in (raw_screenshot_path, *raw_screenshot_path.parents)
                if parent != self._runtime_root
            )
            try:
                resolved_screenshot = raw_screenshot_path.resolve(strict=True)
                screenshot_content = resolved_screenshot.read_bytes()
            except OSError:
                screenshot = None
            else:
                if (
                    screenshot_parent_symlinked
                    or not raw_screenshot_path.is_relative_to(self._runtime_root)
                    or resolved_screenshot.parent != expected_screenshot_directory.resolve()
                    or hashlib.sha256(screenshot_content).hexdigest() != screenshot.sha256
                ):
                    screenshot = None
        expired = action.expires_at is not None and _utc(action.expires_at) <= datetime.now(UTC)
        session_reference_valid = False
        if browser_session is not None and browser_session.external_session_ref:
            supplied_reference = Path(browser_session.external_session_ref)
            expected_reference = (
                self._runtime_root
                / "candidates"
                / action.candidate_id
                / "sessions"
                / str(browser_session.id)
            )
            session_reference_valid = (
                not supplied_reference.is_symlink()
                and not any(
                    parent.is_symlink()
                    for parent in supplied_reference.parents
                    if parent != self._runtime_root
                )
                and supplied_reference.resolve() == expected_reference.resolve()
                and supplied_reference.is_dir()
            )
        browser_status = (
            browser_session.status
            if browser_session is not None
            and browser_session.candidate_id == action.candidate_id
            and browser_session.application_id == action.application_id
            and session_reference_valid
            else None
        )
        browser_health = (
            {
                "human_action_required": "paused",
                "human_takeover_opened": "takeover_opened",
                "queued": "resuming",
                "ready": "ready",
                "failed": "failed",
                "cancelled": "closed",
                "retained_metadata": "expired",
            }.get(browser_status, "unavailable")
            if browser_status is not None
            else "unavailable"
        )
        if expired:
            browser_health = "expired"
        # The current local flow records an authenticated handshake but has no interactive broker.
        # Never represent that handshake as a one-time transport capability.
        capability_status = "not_required" if action.browser_session_id is None else "unavailable"
        if action.browser_session_id is None:
            handshake_status = "not_required"
        elif expired:
            handshake_status = "expired"
        elif action.status != "pending":
            handshake_status = "closed"
        elif browser_status == "human_action_required":
            handshake_status = "ready_to_open"
        elif browser_status == "human_takeover_opened":
            handshake_status = "opened"
        else:
            handshake_status = "unavailable"
        if expired:
            verifier_state = "expired"
        elif action.status == "completed":
            verifier_state = "verified"
        elif action.status == "cancelled":
            verifier_state = "cancelled"
        elif action.browser_session_id is None:
            verifier_state = "not_required"
        elif browser_status == "human_action_required":
            verifier_state = "awaiting_human"
        elif browser_status == "human_takeover_opened":
            verifier_state = "awaiting_browser_verification"
        else:
            verifier_state = "unavailable"
        source_url = action.payload.get("final_page", {}).get("source_url")
        safe_origin: str | None = None
        if isinstance(source_url, str):
            try:
                parsed = urlsplit(source_url)
                if (
                    parsed.scheme in {"http", "https"}
                    and parsed.hostname in {"127.0.0.1", "localhost"}
                    and parsed.username is None
                    and parsed.password is None
                ):
                    port = parsed.port
                    default_port = 80 if parsed.scheme == "http" else 443
                    port_suffix = f":{port}" if port is not None and port != default_port else ""
                    safe_origin = f"{parsed.scheme}://{parsed.hostname}{port_suffix}"
            except ValueError:
                safe_origin = None
        pending = action.status == "pending" and not expired
        continue_available = pending and (
            action.browser_session_id is None
            or browser_status in {"human_action_required", "human_takeover_opened"}
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
            screenshot_available=screenshot is not None,
            screenshot_artifact_id=screenshot.id if screenshot is not None else None,
            screenshot_sha256=screenshot.sha256 if screenshot is not None else None,
            screenshot_download_path=(
                f"/api/applications/{action.application_id}/artifacts/{screenshot.id}"
                f"?candidate_id={action.candidate_id}"
                if screenshot is not None
                else None
            ),
            browser_session_id=action.browser_session_id,
            session_opened=browser_status == "human_takeover_opened",
            browser_session_health=browser_health,
            safe_origin=safe_origin,
            takeover_capability_status=capability_status,
            takeover_handshake_status=handshake_status,
            verifier_state=verifier_state,
            continue_available=continue_available,
            cancel_available=pending,
            continue_consequence=(
                "After browser verification, Career OS resumes this same isolated dry run; "
                "this does not authorize submission."
                if action.browser_session_id is not None
                else "Career OS records the reviewed action and continues to backend validation; "
                "this does not authorize submission."
            ),
            cancel_consequence=(
                "Career OS cancels this workflow and withdraws the application; no submission "
                "is attempted."
            ),
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

    def get_controlled_submission(
        self, candidate_id: str, application_id: UUID
    ) -> ControlledSubmissionExecutionView:
        self._candidates.get_config(candidate_id)
        with self._sessions() as session:
            application = self._application(session, candidate_id, application_id)
            attempt = session.scalar(
                select(ControlledSubmissionAttempt)
                .where(
                    ControlledSubmissionAttempt.candidate_id == candidate_id,
                    ControlledSubmissionAttempt.application_id == application_id,
                )
                .order_by(
                    ControlledSubmissionAttempt.created_at.desc(),
                    ControlledSubmissionAttempt.id.desc(),
                )
                .limit(1)
            )
            if attempt is None:
                raise ApplicationNotFoundError("controlled submission was not found")
            return self._controlled_submission_view(application, attempt)

    def reconcile_stale_controlled_submissions(
        self,
        candidate_id: str,
        *,
        now: datetime | None = None,
        grace: timedelta = timedelta(minutes=2),
    ) -> int:
        """Turn abandoned click barriers into non-retryable unknown outcomes without clicking."""

        current = now or datetime.now(UTC)
        cutoff = current - grace
        with self._candidates.lifecycle_write(candidate_id):
            with self._sessions() as lookup:
                attempt_ids = tuple(
                    lookup.scalars(
                        select(ControlledSubmissionAttempt.id).where(
                            ControlledSubmissionAttempt.candidate_id == candidate_id,
                            ControlledSubmissionAttempt.status == "click_authorized",
                            ControlledSubmissionAttempt.click_boundary_entered_at <= cutoff,
                        )
                    ).all()
                )
            reconciled = 0
            for attempt_id in attempt_ids:
                receipt_path = (
                    self._controlled_evidence_directory(candidate_id, attempt_id)
                    / "unknown_outcome.json"
                )
                if not receipt_path.exists():
                    self._write_controlled_evidence(
                        receipt_path,
                        canonical_json_bytes(
                            {
                                "attempt_id": str(attempt_id),
                                "status": "unknown_after_click",
                                "retryable": False,
                                "category": "click_worker_abandoned",
                                "recorded_at": current,
                            }
                        ),
                    )
                receipt_sha256 = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
                with self._sessions.begin() as session:
                    attempt = session.scalar(
                        select(ControlledSubmissionAttempt)
                        .where(ControlledSubmissionAttempt.id == attempt_id)
                        .with_for_update()
                    )
                    if (
                        attempt is None
                        or attempt.candidate_id != candidate_id
                        or attempt.status != "click_authorized"
                        or attempt.click_boundary_entered_at is None
                        or _utc(attempt.click_boundary_entered_at) > cutoff
                    ):
                        continue
                    application = self._application(session, candidate_id, attempt.application_id)
                    attempt.status = "unknown_after_click"
                    attempt.failure_category = "click_worker_abandoned"
                    attempt.finalized_at = current
                    attempt.final_evidence_sha256 = receipt_sha256
                    self._transition(
                        session,
                        application,
                        ApplicationState.UNKNOWN_AFTER_CLICK,
                        f"controlled-task:{attempt.task_id}:abandoned",
                        "CONTROLLED_SUBMISSION_OUTCOME_UNKNOWN",
                        payload={
                            "attempt_id": str(attempt.id),
                            "category": "click_worker_abandoned",
                            "retryable": False,
                            "receipt_sha256": receipt_sha256,
                        },
                    )
                    session.add(
                        ApplicationArtifact(
                            candidate_id=candidate_id,
                            application_id=application.id,
                            kind="controlled_submission_unknown_receipt",
                            version=1,
                            storage_uri=str(receipt_path),
                            sha256=receipt_sha256,
                            content_type="application/json",
                            immutable=True,
                            artifact_metadata={
                                "attempt_id": str(attempt.id),
                                "backend_confirmed": False,
                                "retryable": False,
                            },
                        )
                    )
                    session.add(
                        HumanAction(
                            candidate_id=candidate_id,
                            application_id=application.id,
                            actor_id="controlled-submission-reconciler",
                            action=HumanActionKind.PAUSE,
                            kind="submission_outcome_unknown",
                            status="pending",
                            reason="Submission outcome is unknown; do not retry.",
                            browser_session_id=attempt.browser_session_id,
                            payload={"attempt_id": str(attempt.id), "retryable": False},
                        )
                    )
                    session.add(
                        NotificationRecord(
                            candidate_id=candidate_id,
                            application_id=application.id,
                            event_type="submission_outcome_unknown",
                            channel="dashboard",
                            message="Submission outcome is unknown; do not retry.",
                            immediate=True,
                        )
                    )
                    if attempt.task_id is not None:
                        workflow_task = session.get(WorkflowTask, attempt.task_id)
                        if workflow_task is not None:
                            workflow_task.status = "failed"
                            workflow_task.last_error = "click_worker_abandoned"
                            workflow_task.last_error_category = "click_worker_abandoned"
                            workflow_task.last_error_retryable = False
                            workflow_task.locked_by = None
                            workflow_task.locked_at = None
                    reconciled += 1
            return reconciled

    def _validate_controlled_policy(
        self,
        session: Session,
        config: CandidateConfig,
        settings: CandidateSettingsRecord,
        job: GlobalJob | None,
        *,
        approval_acknowledged: bool,
    ) -> str:
        if not self._controlled_submission_enabled:
            raise ApplicationConflictError("controlled submission is disabled")
        if not config.manifest.workflow.automatic_submission_enabled:
            raise ApplicationConflictError("candidate automatic submission is disabled")
        if settings.emergency_stopped:
            raise ApplicationConflictError("emergency stop is active")
        if settings.automation_mode not in {"approval_required", "autonomous"}:
            raise ApplicationConflictError("candidate automation mode denies controlled submission")
        if settings.automation_mode == "approval_required" and not approval_acknowledged:
            raise ApplicationConflictError("controlled submission approval is required")
        if "greenhouse" not in settings.allowed_ats_adapters:
            raise ApplicationConflictError("Greenhouse is not an allowed ATS adapter")
        settings_view = self._settings_view(session, config, settings)
        if "greenhouse" not in settings_view.tested_ats_adapters:
            raise ApplicationConflictError("Greenhouse has not passed candidate acceptance")
        if settings.automation_mode == "autonomous" and settings_view.autonomy_blockers:
            raise ApplicationConflictError("candidate autonomous readiness is blocked")
        if (
            job is None
            or (job.ats_platform or "").casefold() != "greenhouse"
            or job.application_url is None
        ):
            raise ApplicationConflictError("job is not an exact Greenhouse application target")
        try:
            return GreenhouseControlledAdapter().validate_target(job.application_url)
        except ControlledSubmissionError as exc:
            raise ApplicationConflictError(str(exc)) from exc

    @staticmethod
    def _safe_origin(target_url: str) -> str:
        parsed = urlsplit(target_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.port not in {None, 443}
        ):
            raise ApplicationConflictError("controlled submission target origin is unsafe")
        return f"https://{parsed.hostname}"

    @staticmethod
    def _controlled_submission_view(
        application: Application, attempt: ControlledSubmissionAttempt
    ) -> ControlledSubmissionExecutionView:
        return ControlledSubmissionExecutionView(
            attempt_id=attempt.id,
            application_id=application.id,
            candidate_id=application.candidate_id,
            authorization_id=attempt.authorization_id,
            task_id=attempt.task_id,
            adapter="greenhouse_controlled_v1",
            status=attempt.status,
            application_state=application.state,
            successful=attempt.status == "confirmed"
            and application.state is ApplicationState.CONFIRMED,
            retryable=False,
            confirmation_reference=attempt.confirmation_reference,
            click_boundary_entered_at=attempt.click_boundary_entered_at,
            finalized_at=attempt.finalized_at,
        )

    def _store_controlled_pre_click_evidence(
        self,
        request: ControlledSubmissionPreparationRequest,
        prepared: PreparedControlledSubmission,
    ) -> tuple[Path, Path]:
        directory = self._controlled_evidence_directory(request.candidate_id, request.attempt_id)
        screenshot_path = directory / "pre_click.png"
        page_path = directory / "pre_click.html"
        self._write_controlled_evidence(screenshot_path, prepared.pre_click_screenshot_png)
        self._write_controlled_evidence(page_path, prepared.pre_click_page_html)
        return screenshot_path, page_path

    def _controlled_evidence_directory(self, candidate_id: str, attempt_id: UUID) -> Path:
        if re.fullmatch(r"[a-z][a-z0-9_]{2,63}", candidate_id) is None:
            raise ApplicationConflictError("controlled evidence candidate scope is invalid")
        root = self._runtime_root / "candidates" / candidate_id / "controlled-submissions"
        directory = root / str(attempt_id)
        for path in (root.parent.parent, root.parent, root, directory):
            if path.is_symlink():
                raise ApplicationConflictError("controlled evidence path contains a symlink")
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        directory.chmod(0o700)
        if not directory.resolve().is_relative_to(self._runtime_root):
            raise ApplicationConflictError("controlled evidence path escaped runtime storage")
        return directory

    @staticmethod
    def _write_controlled_evidence(path: Path, content: bytes) -> None:
        if path.is_symlink() or path.exists():
            raise ApplicationConflictError("controlled evidence is immutable")
        path.write_bytes(content)
        path.chmod(0o600)

    def _deny_controlled_before_click(
        self,
        queue: TaskQueue,
        task: TaskView,
        *,
        worker_id: str,
        category: str,
        human_action_kind: str | None,
        now: datetime,
    ) -> TaskView:
        try:
            attempt_id = UUID(str(task.payload["attempt_id"]))
        except (KeyError, ValueError):
            return queue.fail(
                task.task_id,
                worker_id=worker_id,
                category="invalid_controlled_task",
                retryable=False,
                now=now,
            )
        try:
            with self._sessions.begin() as session:
                queue.assert_lease_in_session(
                    session,
                    task.task_id,
                    worker_id=worker_id,
                    expected_attempt=task.attempts,
                )
                attempt = session.get(ControlledSubmissionAttempt, attempt_id)
                if (
                    attempt is None
                    or attempt.candidate_id != task.candidate_id
                    or attempt.task_id != task.task_id
                    or attempt.status != "prepared"
                ):
                    raise ApplicationConflictError("controlled submission denial scope is invalid")
                application = self._application(session, task.candidate_id, attempt.application_id)
                attempt.status = "denied"
                attempt.failure_category = category[:64]
                attempt.finalized_at = now
                event_payload = {
                    "attempt_id": str(attempt.id),
                    "category": category[:64],
                    "human_action_kind": human_action_kind,
                }
                if human_action_kind is None:
                    self._append_same_state_event(
                        session,
                        application,
                        f"controlled-task:{task.task_id}:denied",
                        "CONTROLLED_SUBMISSION_DENIED_BEFORE_CLICK",
                        payload=event_payload,
                    )
                else:
                    browser_session = session.get(BrowserSession, attempt.browser_session_id)
                    if (
                        browser_session is None
                        or browser_session.candidate_id != task.candidate_id
                        or browser_session.application_id != application.id
                    ):
                        raise ApplicationConflictError(
                            "controlled human-action browser session is missing"
                        )
                    browser_session.status = "human_action_required"
                    browser_session.stopped_reason = human_action_kind
                    self._transition(
                        session,
                        application,
                        ApplicationState.HUMAN_ACTION_REQUIRED,
                        f"controlled-task:{task.task_id}:human-action",
                        "CONTROLLED_SUBMISSION_HUMAN_ACTION_REQUIRED",
                        payload=event_payload,
                    )
                    session.add(
                        HumanAction(
                            candidate_id=task.candidate_id,
                            application_id=application.id,
                            actor_id="controlled-submission-worker",
                            action=HumanActionKind.PAUSE,
                            kind=f"controlled_{human_action_kind}",
                            status="pending",
                            reason=(
                                "Controlled submission stopped before click for explicit human "
                                "review. No final POST was sent."
                            ),
                            browser_session_id=browser_session.id,
                            expires_at=now + timedelta(minutes=15),
                            payload={**event_payload, "retryable": False},
                        )
                    )
                    session.add(
                        NotificationRecord(
                            candidate_id=task.candidate_id,
                            application_id=application.id,
                            event_type="controlled_submission_human_action",
                            channel="dashboard",
                            message=(
                                "Controlled submission stopped before click and requires human "
                                "review."
                            ),
                            immediate=True,
                        )
                    )
                return queue.fail_in_session(
                    session,
                    task.task_id,
                    worker_id=worker_id,
                    category=category[:64],
                    retryable=False,
                    now=now,
                    expected_attempt=task.attempts,
                )
        except TaskLeaseLostError:
            current = queue.get(task.task_id)
            if current is None:
                raise
            return current

    def _mark_controlled_unknown(
        self,
        queue: TaskQueue,
        task: TaskView,
        *,
        worker_id: str,
        category: str,
        now: datetime,
    ) -> TaskView:
        attempt_id = UUID(str(task.payload["attempt_id"]))
        receipt_path = (
            self._controlled_evidence_directory(task.candidate_id, attempt_id)
            / "unknown_outcome.json"
        )
        if not receipt_path.exists():
            self._write_controlled_evidence(
                receipt_path,
                canonical_json_bytes(
                    {
                        "attempt_id": str(attempt_id),
                        "status": "unknown_after_click",
                        "retryable": False,
                        "category": category[:64],
                        "recorded_at": now,
                    }
                ),
            )
        receipt_sha256 = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        try:
            with self._sessions.begin() as session:
                queue.assert_lease_in_session(
                    session,
                    task.task_id,
                    worker_id=worker_id,
                    expected_attempt=task.attempts,
                )
                attempt = session.get(ControlledSubmissionAttempt, attempt_id)
                if (
                    attempt is None
                    or attempt.candidate_id != task.candidate_id
                    or attempt.task_id != task.task_id
                    or attempt.status != "click_authorized"
                ):
                    raise ApplicationConflictError("unknown click outcome scope is invalid")
                application = self._application(session, task.candidate_id, attempt.application_id)
                attempt.status = "unknown_after_click"
                attempt.failure_category = category[:64]
                attempt.finalized_at = now
                attempt.final_evidence_sha256 = receipt_sha256
                self._transition(
                    session,
                    application,
                    ApplicationState.UNKNOWN_AFTER_CLICK,
                    f"controlled-task:{task.task_id}:unknown",
                    "CONTROLLED_SUBMISSION_OUTCOME_UNKNOWN",
                    payload={
                        "attempt_id": str(attempt.id),
                        "category": category[:64],
                        "retryable": False,
                        "receipt_sha256": receipt_sha256,
                    },
                )
                session.add(
                    ApplicationArtifact(
                        candidate_id=task.candidate_id,
                        application_id=application.id,
                        kind="controlled_submission_unknown_receipt",
                        version=1,
                        storage_uri=str(receipt_path),
                        sha256=receipt_sha256,
                        content_type="application/json",
                        immutable=True,
                        artifact_metadata={
                            "attempt_id": str(attempt.id),
                            "backend_confirmed": False,
                            "retryable": False,
                        },
                    )
                )
                session.add(
                    HumanAction(
                        candidate_id=task.candidate_id,
                        application_id=application.id,
                        actor_id="controlled-submission-worker",
                        action=HumanActionKind.PAUSE,
                        kind="submission_outcome_unknown",
                        status="pending",
                        reason="Submission outcome is unknown; do not retry.",
                        browser_session_id=attempt.browser_session_id,
                        payload={"attempt_id": str(attempt.id), "retryable": False},
                    )
                )
                session.add(
                    NotificationRecord(
                        candidate_id=task.candidate_id,
                        application_id=application.id,
                        event_type="submission_outcome_unknown",
                        channel="dashboard",
                        message="Submission outcome is unknown; do not retry.",
                        immediate=True,
                    )
                )
                return queue.fail_in_session(
                    session,
                    task.task_id,
                    worker_id=worker_id,
                    category=category[:64],
                    retryable=False,
                    now=now,
                    expected_attempt=task.attempts,
                )
        except TaskLeaseLostError:
            current = queue.get(task.task_id)
            if current is None:
                raise
            return current

    def _confirm_controlled_submission(
        self,
        queue: TaskQueue,
        task: TaskView,
        *,
        worker_id: str,
        result: ControlledSubmissionResult,
        now: datetime,
    ) -> TaskView:
        if result.confirmation_reference is None:
            raise ApplicationConflictError("controlled confirmation reference is missing")
        attempt_id = UUID(str(task.payload["attempt_id"]))
        evidence_directory = self._controlled_evidence_directory(task.candidate_id, attempt_id)
        screenshot_path = evidence_directory / "confirmation.png"
        page_path = evidence_directory / "confirmation.html"
        self._write_controlled_evidence(screenshot_path, result.screenshot_png)
        self._write_controlled_evidence(page_path, result.final_page_html)
        screenshot_sha256 = hashlib.sha256(result.screenshot_png).hexdigest()
        page_sha256 = hashlib.sha256(result.final_page_html).hexdigest()
        final_evidence_sha256 = hashlib.sha256(
            canonical_json_bytes(
                {
                    "confirmation_reference": result.confirmation_reference,
                    "screenshot_sha256": screenshot_sha256,
                    "page_sha256": page_sha256,
                }
            )
        ).hexdigest()
        with self._sessions.begin() as session:
            queue.assert_lease_in_session(
                session,
                task.task_id,
                worker_id=worker_id,
                expected_attempt=task.attempts,
            )
            attempt = session.get(ControlledSubmissionAttempt, attempt_id)
            if (
                attempt is None
                or attempt.candidate_id != task.candidate_id
                or attempt.task_id != task.task_id
                or attempt.status != "click_authorized"
                or result.attempt_id != attempt.id
                or self._safe_origin(result.final_url) != attempt.target_origin
            ):
                raise ApplicationConflictError("controlled confirmation scope is invalid")
            application = self._application(session, task.candidate_id, attempt.application_id)
            if application.state is not ApplicationState.SUBMITTING:
                raise ApplicationConflictError("controlled application is not submitting")
            self._transition(
                session,
                application,
                ApplicationState.SUBMITTED,
                f"controlled-task:{task.task_id}:submitted",
                "CONTROLLED_APPLICATION_SUBMITTED",
                payload={
                    "attempt_id": str(attempt.id),
                    "authorization_id": str(attempt.authorization_id),
                },
            )
            application.confirmation_reference = result.confirmation_reference
            application.submitted_at = now
            application.outcome = ApplicationOutcome.SUBMITTED
            self._transition(
                session,
                application,
                ApplicationState.CONFIRMED,
                f"controlled-task:{task.task_id}:confirmed",
                "SUBMISSION_CONFIRMED",
                payload={
                    "attempt_id": str(attempt.id),
                    "authorization_id": str(attempt.authorization_id),
                    "confirmation_reference": result.confirmation_reference,
                    "backend_confirmed": True,
                    "screenshot_sha256": screenshot_sha256,
                    "page_sha256": page_sha256,
                },
            )
            attempt.status = "confirmed"
            attempt.confirmation_reference = result.confirmation_reference
            attempt.final_evidence_sha256 = final_evidence_sha256
            attempt.finalized_at = now
            browser_session = session.get(BrowserSession, attempt.browser_session_id)
            if browser_session is not None:
                browser_session.status = "confirmed"
            if application.archive_uri is None:
                raise ApplicationConflictError("pre-submit archive is missing")
            events = session.scalars(
                select(ApplicationEvent)
                .where(
                    ApplicationEvent.candidate_id == task.candidate_id,
                    ApplicationEvent.application_id == application.id,
                )
                .order_by(ApplicationEvent.occurred_at, ApplicationEvent.id)
            ).all()
            pre_submit_archive = Path(application.archive_uri)
            confirmed_archive = self._archives.finalize_confirmed(
                pre_submit_archive,
                confirmation_reference=result.confirmation_reference,
                submitted_at=now,
                event_log=[
                    {
                        "event_type": item.event_type,
                        "occurred_at": item.occurred_at,
                        "payload": item.payload,
                    }
                    for item in events
                ],
                synthetic_only=False,
                confirmation_screenshot=result.screenshot_png,
                final_page_snapshot=result.final_page_html,
            )
            application.archive_uri = str(confirmed_archive)
            confirmed_files = {
                "manifest.json": ("archive_manifest", 2, "application/json"),
                "submission/receipt.json": (
                    "submission_receipt",
                    2,
                    "application/json",
                ),
                "submission/confirmation.html": (
                    "submission_confirmation",
                    1,
                    "text/html",
                ),
                "submission/confirmation_screenshot.png": (
                    "submission_confirmation_screenshot",
                    1,
                    "image/png",
                ),
                "submission/final_page_snapshot.html": (
                    "submission_final_page_snapshot",
                    2,
                    "text/html",
                ),
            }
            for relative_path, (kind, version, content_type) in confirmed_files.items():
                path = confirmed_archive / relative_path
                session.add(
                    ApplicationArtifact(
                        candidate_id=task.candidate_id,
                        application_id=application.id,
                        kind=kind,
                        version=version,
                        storage_uri=str(path),
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                        content_type=content_type,
                        immutable=True,
                        artifact_metadata={
                            "attempt_id": str(attempt.id),
                            "archive_uri": str(confirmed_archive),
                            "pre_submit_archive_uri": str(pre_submit_archive),
                            "relative_path": relative_path,
                            "backend_confirmed": True,
                            "synthetic_only": False,
                        },
                    )
                )
            session.add(
                NotificationRecord(
                    candidate_id=task.candidate_id,
                    application_id=application.id,
                    event_type="submission_confirmed",
                    channel="dashboard",
                    message="Controlled Greenhouse submission was backend-confirmed.",
                    immediate=True,
                )
            )
            return queue.complete_in_session(
                session,
                task.task_id,
                worker_id=worker_id,
                now=now,
                expected_attempt=task.attempts,
            )

    @staticmethod
    def _default_settings_record(candidate_id: str) -> CandidateSettingsRecord:
        return CandidateSettingsRecord(
            candidate_id=candidate_id,
            automation_mode="approval_required",
            discovery_enabled=False,
            emergency_stopped=False,
            allowed_ats_adapters=[],
            tested_ats_adapters=[],
            dry_run_acceptance_passed=False,
            explicit_autonomy_confirmation=False,
            autonomy_confirmation_scope_sha256=None,
            autonomy_confirmed_at=None,
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
                select(func.count(func.distinct(Application.id)))
                .outerjoin(
                    ControlledSubmissionAttempt,
                    (ControlledSubmissionAttempt.candidate_id == Application.candidate_id)
                    & (ControlledSubmissionAttempt.application_id == Application.id),
                )
                .where(
                    Application.candidate_id == candidate_id,
                    or_(
                        Application.submitted_at >= day_start,
                        ControlledSubmissionAttempt.click_boundary_entered_at >= day_start,
                    ),
                )
            )
            or 0
        )
        submitted_week = (
            session.scalar(
                select(func.count(func.distinct(Application.id)))
                .outerjoin(
                    ControlledSubmissionAttempt,
                    (ControlledSubmissionAttempt.candidate_id == Application.candidate_id)
                    & (ControlledSubmissionAttempt.application_id == Application.id),
                )
                .where(
                    Application.candidate_id == candidate_id,
                    or_(
                        Application.submitted_at >= now - timedelta(days=7),
                        ControlledSubmissionAttempt.click_boundary_entered_at
                        >= now - timedelta(days=7),
                    ),
                )
            )
            or 0
        )
        submitted_company = (
            session.scalar(
                select(func.count(func.distinct(Application.id)))
                .join(GlobalJob, GlobalJob.id == Application.job_id)
                .outerjoin(
                    ControlledSubmissionAttempt,
                    (ControlledSubmissionAttempt.candidate_id == Application.candidate_id)
                    & (ControlledSubmissionAttempt.application_id == Application.id),
                )
                .where(
                    Application.candidate_id == candidate_id,
                    or_(
                        Application.submitted_at >= now - timedelta(days=30),
                        ControlledSubmissionAttempt.click_boundary_entered_at
                        >= now - timedelta(days=30),
                    ),
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
    def _dry_run_manifest_passed(manifest: BrowserAttemptManifest) -> bool:
        return (
            manifest.final_submit_present
            and not manifest.final_submit_clicked
            and manifest.allowed_network_requests == 1
            and manifest.blocked_network_requests >= 2
            and bool(manifest.upload_hashes)
        )

    @staticmethod
    def _browser_manifest_artifact(
        session: Session,
        application: Application,
        manifest: BrowserAttemptManifest,
    ) -> ApplicationArtifact:
        matching = tuple(
            item
            for item in session.scalars(
                select(ApplicationArtifact).where(
                    ApplicationArtifact.candidate_id == application.candidate_id,
                    ApplicationArtifact.application_id == application.id,
                    ApplicationArtifact.kind == "browser_attempt_manifest",
                    ApplicationArtifact.immutable.is_(True),
                )
            ).all()
            if item.artifact_metadata.get("task_id") == str(manifest.task_id)
            and item.artifact_metadata.get("attempt") == manifest.attempt
            and item.artifact_metadata.get("session_id") == str(manifest.session_id)
        )
        if len(matching) != 1:
            raise ApplicationConflictError("browser manifest evidence is ambiguous")
        return matching[0]

    def _valid_dry_run_evidence(
        self, session: Session, candidate_id: str
    ) -> tuple[tuple[Application, BrowserAttemptManifest, ApplicationArtifact], ...]:
        valid: list[tuple[Application, BrowserAttemptManifest, ApplicationArtifact]] = []
        applications = session.scalars(
            select(Application)
            .where(Application.candidate_id == candidate_id)
            .order_by(Application.updated_at.desc(), Application.id.desc())
        ).all()
        for application in applications:
            try:
                manifest, _screenshot, _final_page = self._verified_browser_evidence(
                    session, application
                )
                artifact = self._browser_manifest_artifact(session, application, manifest)
            except ApplicationConflictError:
                continue
            if self._dry_run_manifest_passed(manifest):
                valid.append((application, manifest, artifact))
        return tuple(valid)

    @staticmethod
    def _adapter_acceptance_package_sha256(
        result: SyntheticAdapterAcceptanceResult,
        manifest: BrowserAttemptManifest,
        evidence_manifest_sha256: str,
    ) -> str:
        return hashlib.sha256(
            canonical_json_bytes(
                {
                    "adapter_acceptance": result.model_dump(mode="json"),
                    "candidate_id": manifest.candidate_id,
                    "application_id": str(manifest.application_id),
                    "browser_task_id": str(manifest.task_id),
                    "browser_attempt": manifest.attempt,
                    "dry_run_manifest_sha256": evidence_manifest_sha256,
                    "upload_hashes": list(manifest.upload_hashes),
                }
            )
        ).hexdigest()

    def _valid_adapter_acceptances(
        self, session: Session, candidate_id: str
    ) -> tuple[AtsAdapterAcceptanceRecord, ...]:
        valid: list[AtsAdapterAcceptanceRecord] = []
        records = session.scalars(
            select(AtsAdapterAcceptanceRecord)
            .where(
                AtsAdapterAcceptanceRecord.candidate_id == candidate_id,
                AtsAdapterAcceptanceRecord.passed.is_(True),
            )
            .order_by(AtsAdapterAcceptanceRecord.recorded_at.desc())
        ).all()
        for record in records:
            application = session.get(Application, record.application_id)
            if application is None or application.candidate_id != candidate_id:
                continue
            try:
                manifest, _screenshot, _final_page = self._verified_browser_evidence(
                    session, application
                )
                manifest_artifact = self._browser_manifest_artifact(session, application, manifest)
                review = session.scalar(
                    select(AgentReview)
                    .where(
                        AgentReview.candidate_id == candidate_id,
                        AgentReview.application_id == application.id,
                    )
                    .order_by(AgentReview.created_at.desc(), AgentReview.id.desc())
                    .limit(1)
                )
                if review is None:
                    continue
                result = SyntheticGreenhouseAcceptanceRunner().run(
                    self._controlled_form_payload(session, application, review)
                )
            except (ApplicationConflictError, ValueError):
                continue
            expected_package = self._adapter_acceptance_package_sha256(
                result, manifest, manifest_artifact.sha256
            )
            if (
                self._dry_run_manifest_passed(manifest)
                and record.browser_task_id == manifest.task_id
                and record.browser_attempt == manifest.attempt
                and record.evidence_manifest_sha256 == manifest_artifact.sha256
                and record.adapter == result.adapter
                and record.adapter_version == result.adapter_version
                and record.destination_policy_sha256 == result.destination_policy_sha256
                and record.form_pattern == result.form_pattern
                and record.form_fingerprint == result.form_fingerprint
                and hmac.compare_digest(record.package_sha256, expected_package)
            ):
                valid.append(record)
        return tuple(valid)

    def _autonomy_scope_sha256(
        self,
        config: CandidateConfig,
        record: CandidateSettingsRecord,
        acceptances: tuple[AtsAdapterAcceptanceRecord, ...],
        dry_run_evidence: tuple[
            tuple[Application, BrowserAttemptManifest, ApplicationArtifact], ...
        ] = (),
    ) -> str:
        return hashlib.sha256(
            canonical_json_bytes(
                {
                    "candidate_id": record.candidate_id,
                    "profile_version": config.manifest.profile_version,
                    "automatic_submission_enabled": (
                        config.manifest.workflow.automatic_submission_enabled
                    ),
                    "allowed_ats_adapters": sorted(record.allowed_ats_adapters),
                    "acceptance_evidence": [
                        {
                            "id": str(item.id),
                            "adapter": item.adapter,
                            "adapter_version": item.adapter_version,
                            "destination_policy_sha256": item.destination_policy_sha256,
                            "form_fingerprint": item.form_fingerprint,
                            "package_sha256": item.package_sha256,
                        }
                        for item in sorted(acceptances, key=lambda item: str(item.id))
                    ],
                    "dry_run_evidence": [
                        {
                            "application_id": str(application.id),
                            "task_id": str(manifest.task_id),
                            "attempt": manifest.attempt,
                            "manifest_sha256": artifact.sha256,
                        }
                        for application, manifest, artifact in dry_run_evidence
                    ],
                    "limits": {
                        "daily": record.maximum_applications_per_day,
                        "weekly": record.maximum_applications_per_week,
                        "per_company_30_days": (record.maximum_applications_per_company_30_days),
                    },
                    "consequence_version": self._AUTONOMY_CONSEQUENCE_VERSION,
                    "emergency_stop_blocks_new_submissions": True,
                }
            )
        ).hexdigest()

    @staticmethod
    def _autonomy_prerequisites(
        candidate_id: str,
        blockers: list[str],
        acceptances: tuple[AtsAdapterAcceptanceRecord, ...],
        dry_run_evidence: tuple[
            tuple[Application, BrowserAttemptManifest, ApplicationArtifact], ...
        ],
        confirmed_at: datetime | None,
    ) -> tuple[AutonomyPrerequisiteView, ...]:
        blocked = set(blockers)
        acceptance = acceptances[0] if acceptances else None
        dry_run = dry_run_evidence[0] if dry_run_evidence else None
        encoded_candidate = candidate_id
        definitions = (
            (
                "no_allowed_ats_adapter",
                "Allow one ATS adapter",
                (
                    "A tested adapter can close autonomy readiness only when the candidate has "
                    "explicitly allowed that ATS platform."
                ),
                "Choose the ATS adapters that may be used before running an acceptance check.",
                f"/settings?candidate_id={encoded_candidate}#allowed-ats-adapters",
                None,
                None,
                None,
            ),
            (
                "no_tested_ats_adapter",
                "Test one ATS adapter safely",
                (
                    "A network-free acceptance check must exercise the controlled adapter code "
                    "for an exact form pattern."
                ),
                (
                    "Complete a safe dry run, then run the synthetic adapter check for that "
                    "application."
                ),
                f"/applications?candidate_id={encoded_candidate}",
                acceptance.id if acceptance else None,
                (
                    f"{acceptance.adapter} {acceptance.adapter_version}; "
                    f"form {acceptance.form_fingerprint[:12]}…"
                    if acceptance
                    else None
                ),
                acceptance.recorded_at if acceptance else None,
            ),
            (
                "dry_run_acceptance_not_passed",
                "Complete a safe browser dry run",
                (
                    "Career OS needs hash-verified candidate-scoped browser evidence showing the "
                    "final page without a submit click."
                ),
                "Open a prepared application and run the isolated dry run.",
                f"/applications?candidate_id={encoded_candidate}",
                dry_run[0].id if dry_run else None,
                (
                    f"Application {dry_run[0].id}; task {dry_run[1].task_id}; submit clicked: no"
                    if dry_run
                    else None
                ),
                dry_run[1].completed_at if dry_run else None,
            ),
            (
                "explicit_confirmation_missing",
                "Confirm the autonomous scope yourself",
                (
                    "Only you can accept the displayed limits, tested adapter scope, and "
                    "emergency-stop consequences."
                ),
                "After evidence passes, review the consequences and check the confirmation box.",
                f"/settings?candidate_id={encoded_candidate}#autonomy-confirmation",
                None,
                "Audited user confirmation is current." if confirmed_at else None,
                confirmed_at,
            ),
        )
        return tuple(
            AutonomyPrerequisiteView(
                code=code,
                title=title,
                explanation=explanation,
                passed=code not in blocked,
                resolution=resolution,
                action_href=action_href,
                evidence_id=evidence_id,
                evidence_summary=evidence_summary,
                evidenced_at=evidenced_at,
            )
            for (
                code,
                title,
                explanation,
                resolution,
                action_href,
                evidence_id,
                evidence_summary,
                evidenced_at,
            ) in definitions
        )

    def _settings_view(
        self,
        session: Session,
        config: CandidateConfig,
        record: CandidateSettingsRecord,
        *,
        acceptances: tuple[AtsAdapterAcceptanceRecord, ...] | None = None,
        ignore_confirmation: bool = False,
    ) -> SettingsView:
        all_valid_acceptances = (
            acceptances
            if acceptances is not None
            else self._valid_adapter_acceptances(session, record.candidate_id)
        )
        valid_acceptances = tuple(
            item for item in all_valid_acceptances if item.adapter in record.allowed_ats_adapters
        )
        dry_run_evidence = self._valid_dry_run_evidence(session, record.candidate_id)
        tested_adapters = tuple(sorted({item.adapter for item in valid_acceptances}))
        dry_run_acceptance_passed = bool(dry_run_evidence)
        expected_scope = self._autonomy_scope_sha256(
            config, record, valid_acceptances, dry_run_evidence
        )
        explicit_confirmation = (
            not ignore_confirmation
            and record.explicit_autonomy_confirmation
            and record.autonomy_confirmation_scope_sha256 is not None
            and hmac.compare_digest(record.autonomy_confirmation_scope_sha256, expected_scope)
        )
        blockers: list[str] = []
        if not config.manifest.validation.profile_approved:
            blockers.append("profile_not_approved")
        if not config.manifest.validation.legal_status_approved:
            blockers.append("legal_status_not_approved")
        if not config.manifest.validation.automatic_answers_approved:
            blockers.append("automatic_answers_not_approved")
        if not config.manifest.validation.cv_templates_approved:
            blockers.append("cv_templates_not_approved")
        if not config.manifest.workflow.automatic_submission_enabled:
            blockers.append("automatic_submission_disabled")
        if not record.allowed_ats_adapters:
            blockers.append("no_allowed_ats_adapter")
        if not tested_adapters:
            blockers.append("no_tested_ats_adapter")
        if not dry_run_acceptance_passed:
            blockers.append("dry_run_acceptance_not_passed")
        if not explicit_confirmation:
            blockers.append("explicit_confirmation_missing")
        if record.emergency_stopped:
            blockers.append("emergency_stop_active")
        return SettingsView(
            candidate_id=record.candidate_id,
            automation_mode=record.automation_mode,
            discovery_enabled=record.discovery_enabled,
            emergency_stopped=record.emergency_stopped,
            allowed_ats_adapters=tuple(record.allowed_ats_adapters),
            tested_ats_adapters=tested_adapters,
            dry_run_acceptance_passed=dry_run_acceptance_passed,
            explicit_autonomy_confirmation=explicit_confirmation,
            maximum_applications_per_day=record.maximum_applications_per_day,
            maximum_applications_per_week=record.maximum_applications_per_week,
            maximum_applications_per_company_30_days=(
                record.maximum_applications_per_company_30_days
            ),
            browser_session_retention_days=record.browser_session_retention_days,
            autonomy_blockers=tuple(blockers),
            autonomy_prerequisites=self._autonomy_prerequisites(
                record.candidate_id,
                blockers,
                valid_acceptances,
                dry_run_evidence,
                record.autonomy_confirmed_at if explicit_confirmation else None,
            ),
            controlled_submission_enabled=self._controlled_submission_enabled,
        )
