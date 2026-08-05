from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.enums import (
    ApplicationOutcome,
    ApplicationState,
    DocumentKind,
    HumanActionKind,
    ReviewDecision,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSON}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class CandidateScopedMixin:
    candidate_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class GlobalJob(Base, TimestampMixin):
    __tablename__ = "global_jobs"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_global_job_source_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    location: Mapped[str | None] = mapped_column(String(255))
    normalized_title: Mapped[str | None] = mapped_column(String(255), index=True)
    normalized_location: Mapped[str | None] = mapped_column(String(255))
    company_domain: Mapped[str | None] = mapped_column(String(255), index=True)
    requisition_id: Mapped[str | None] = mapped_column(String(255), index=True)
    application_url: Mapped[str | None] = mapped_column(Text)
    ats_platform: Mapped[str | None] = mapped_column(String(50), index=True)
    remote_policy: Mapped[str | None] = mapped_column(String(50))
    employment_type: Mapped[str | None] = mapped_column(String(50))
    seniority: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    description_normalized: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    required_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    preferred_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    required_languages: Mapped[list[str]] = mapped_column(JSON, default=list)
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    salary_period: Mapped[str | None] = mapped_column(String(50))
    source_trust_level: Mapped[str] = mapped_column(String(32), default="unverified")
    verified_open_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    semantic_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    security_findings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class JobVersion(Base):
    """Append-only normalized snapshots of external job data."""

    __tablename__ = "job_versions"
    __table_args__ = (
        UniqueConstraint("job_id", "version", name="uq_job_version"),
        UniqueConstraint("job_id", "payload_sha256", name="uq_job_version_payload"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("global_jobs.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CandidateJobScore(Base, TimestampMixin, CandidateScopedMixin):
    __tablename__ = "candidate_job_scores"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "job_id", "scoring_version", name="uq_candidate_job_score"
        ),
        UniqueConstraint("candidate_id", "job_id", "id", name="uq_candidate_job_score_scope"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("global_jobs.id"), nullable=False, index=True
    )
    scoring_version: Mapped[int] = mapped_column(Integer, nullable=False)
    total_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    rationale: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    meets_threshold: Mapped[bool] = mapped_column(Boolean, nullable=False)


class CandidateJobDecision(Base, TimestampMixin, CandidateScopedMixin):
    """Candidate-owned inbox state and idempotent command receipt for a global job."""

    __tablename__ = "candidate_job_decisions"
    __table_args__ = (UniqueConstraint("candidate_id", "job_id", name="uq_candidate_job_decision"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("global_jobs.id"), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="discovered")
    verified_open_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CandidateJobCommand(Base, CandidateScopedMixin):
    __tablename__ = "candidate_job_commands"
    __table_args__ = (
        UniqueConstraint("candidate_id", "idempotency_key", name="uq_candidate_job_command"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("global_jobs.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    command: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CandidateDiscoveryCommand(Base, CandidateScopedMixin):
    """Durable request receipt for candidate-scoped discovery commands."""

    __tablename__ = "candidate_discovery_commands"
    __table_args__ = (
        UniqueConstraint("candidate_id", "idempotency_key", name="uq_candidate_discovery_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CandidateDiscoverySource(Base, TimestampMixin, CandidateScopedMixin):
    """Candidate-owned, read-only ATS board scheduled for periodic discovery."""

    __tablename__ = "candidate_discovery_sources"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "provider", "board_token", name="uq_candidate_discovery_source"
        ),
        UniqueConstraint(
            "candidate_id", "idempotency_key", name="uq_candidate_discovery_source_command"
        ),
        UniqueConstraint("candidate_id", "id", name="uq_candidate_discovery_source_scope"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    company_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    board_token: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cadence_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, index=True
    )
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(64))


class CandidateDiscoverySourceCommand(Base, CandidateScopedMixin):
    """Payload-bound receipt for a discovery source mutation."""

    __tablename__ = "candidate_discovery_source_commands"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "idempotency_key", name="uq_candidate_discovery_source_update_key"
        ),
        ForeignKeyConstraint(
            ["candidate_id", "source_id"],
            ["candidate_discovery_sources.candidate_id", "candidate_discovery_sources.id"],
            name="fk_discovery_source_command_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_discovery_sources.id"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CandidateDiscoveryRun(Base, CandidateScopedMixin):
    """Durable status for one cadence-bucket execution of a discovery source."""

    __tablename__ = "candidate_discovery_runs"
    __table_args__ = (
        UniqueConstraint("source_id", "cadence_bucket", name="uq_discovery_run_bucket"),
        ForeignKeyConstraint(
            ["candidate_id", "source_id"],
            ["candidate_discovery_sources.candidate_id", "candidate_discovery_sources.id"],
            name="fk_discovery_run_source_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_discovery_sources.id"), nullable=False, index=True
    )
    cadence_bucket: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="scheduled")
    discovered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    lease_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowTask(Base, TimestampMixin, CandidateScopedMixin):
    """Durable worker task with candidate scope, leasing, and replay protection."""

    __tablename__ = "workflow_tasks"
    __table_args__ = (
        UniqueConstraint("candidate_id", "idempotency_key", name="uq_workflow_task_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    locked_by: Mapped[str | None] = mapped_column(String(128))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdministrativeAuditRecord(Base, CandidateScopedMixin):
    """Hash-chained administrative access and policy mutation record."""

    __tablename__ = "administrative_audit_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Application(Base, TimestampMixin, CandidateScopedMixin):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("candidate_id", "job_id", name="uq_candidate_application_job"),
        UniqueConstraint("candidate_id", "id", name="uq_application_scope"),
        ForeignKeyConstraint(
            ["candidate_id", "job_id", "score_id"],
            [
                "candidate_job_scores.candidate_id",
                "candidate_job_scores.job_id",
                "candidate_job_scores.id",
            ],
            name="fk_application_candidate_score",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("global_jobs.id"), nullable=False, index=True
    )
    score_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("candidate_job_scores.id"))
    state: Mapped[ApplicationState] = mapped_column(
        Enum(ApplicationState, native_enum=False), default=ApplicationState.DISCOVERED
    )
    outcome: Mapped[ApplicationOutcome] = mapped_column(
        Enum(ApplicationOutcome, native_enum=False), default=ApplicationOutcome.PENDING
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    terminal_reason: Mapped[str | None] = mapped_column(Text)
    archive_uri: Mapped[str | None] = mapped_column(Text)
    confirmation_reference: Mapped[str | None] = mapped_column(String(255))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApplicationDocument(Base, TimestampMixin, CandidateScopedMixin):
    __tablename__ = "application_documents"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "application_id", "kind", "version", name="uq_application_document"
        ),
        ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_application_document_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    kind: Mapped[DocumentKind] = mapped_column(Enum(DocumentKind, native_enum=False))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_ids: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validated: Mapped[bool] = mapped_column(Boolean, default=False)


class ApplicationAnswer(Base, TimestampMixin, CandidateScopedMixin):
    __tablename__ = "application_answers"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "application_id", "question_key", name="uq_application_answer"
        ),
        ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_application_answer_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    question_key: Mapped[str] = mapped_column(String(255), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    approved_source_key: Mapped[str | None] = mapped_column(String(255))
    evidence_ids: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    supported: Mapped[bool] = mapped_column(Boolean, default=False)


class ApplicationEvent(Base, CandidateScopedMixin):
    __tablename__ = "application_events"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "application_id", "idempotency_key", name="uq_application_event_key"
        ),
        Index("ix_application_events_timeline", "candidate_id", "application_id", "occurred_at"),
        ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_application_event_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    from_state: Mapped[ApplicationState] = mapped_column(Enum(ApplicationState, native_enum=False))
    to_state: Mapped[ApplicationState] = mapped_column(Enum(ApplicationState, native_enum=False))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SecurityEvent(Base, CandidateScopedMixin):
    __tablename__ = "security_events"
    __table_args__ = (
        Index("ix_security_events_candidate_time", "candidate_id", "occurred_at"),
        ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_security_event_application_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BrowserSession(Base, TimestampMixin, CandidateScopedMixin):
    __tablename__ = "browser_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_browser_session_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    authorization_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    external_session_ref: Mapped[str | None] = mapped_column(String(255))
    stopped_reason: Mapped[str | None] = mapped_column(Text)


class HumanAction(Base, CandidateScopedMixin):
    __tablename__ = "human_actions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_human_action_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[HumanActionKind] = mapped_column(Enum(HumanActionKind, native_enum=False))
    reason: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    kind: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    browser_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("browser_sessions.id"))
    screenshot_uri: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Interview(Base, TimestampMixin, CandidateScopedMixin):
    __tablename__ = "interviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_interview_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(100), nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class Offer(Base, TimestampMixin, CandidateScopedMixin):
    __tablename__ = "offers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_offer_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3))
    base_compensation: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    offered_on: Mapped[date | None] = mapped_column(Date)
    expires_on: Mapped[date | None] = mapped_column(Date)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AgentReview(Base, TimestampMixin, CandidateScopedMixin):
    """Persisted independent review result used by the gate's evidence trail."""

    __tablename__ = "agent_reviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_agent_review_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    decision: Mapped[ReviewDecision] = mapped_column(Enum(ReviewDecision, native_enum=False))
    semantic_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class SubmissionAuthorizationRecord(Base, CandidateScopedMixin):
    """Durable, one-time record of a gate-issued final submission authorization."""

    __tablename__ = "submission_authorizations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_submission_authorization_scope",
        ),
    )

    authorization_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    workflow_state: Mapped[ApplicationState] = mapped_column(
        Enum(ApplicationState, native_enum=False), nullable=False
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    package_sha256: Mapped[str | None] = mapped_column(String(64))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CandidateSnapshotRecord(Base, CandidateScopedMixin):
    __tablename__ = "candidate_snapshot_records"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "application_id", "profile_version", name="uq_snapshot_profile"
        ),
        ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_candidate_snapshot_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    profile_version: Mapped[str] = mapped_column(String(32), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ApplicationArtifact(Base, CandidateScopedMixin):
    __tablename__ = "application_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "application_id", "kind", "version", name="uq_application_artifact"
        ),
        ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_application_artifact_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CandidateSettingsRecord(Base, TimestampMixin, CandidateScopedMixin):
    __tablename__ = "candidate_settings"
    __table_args__ = (UniqueConstraint("candidate_id", name="uq_candidate_settings"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    automation_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="dry_run")
    discovery_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    emergency_stopped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allowed_ats_adapters: Mapped[list[str]] = mapped_column(JSON, default=list)
    tested_ats_adapters: Mapped[list[str]] = mapped_column(JSON, default=list)
    dry_run_acceptance_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    explicit_autonomy_confirmation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    maximum_applications_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    maximum_applications_per_week: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    maximum_applications_per_company_30_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )


class NotificationRecord(Base, CandidateScopedMixin):
    __tablename__ = "notifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_notification_application_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="dashboard")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    immediate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CorrespondenceRecord(Base, CandidateScopedMixin):
    __tablename__ = "correspondence_records"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "external_message_id", name="uq_correspondence_external_message"
        ),
        ForeignKeyConstraint(
            ["candidate_id", "application_id"],
            ["applications.candidate_id", "applications.id"],
            name="fk_correspondence_application_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id"), nullable=True, index=True
    )
    external_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    sender: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    body_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
