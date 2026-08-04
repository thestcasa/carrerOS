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
    description: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CandidateJobScore(Base, TimestampMixin, CandidateScopedMixin):
    __tablename__ = "candidate_job_scores"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "job_id", "scoring_version", name="uq_candidate_job_score"
        ),
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


class Application(Base, TimestampMixin, CandidateScopedMixin):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("candidate_id", "job_id", name="uq_candidate_application_job"),
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
    terminal_reason: Mapped[str | None] = mapped_column(Text)


class ApplicationDocument(Base, TimestampMixin, CandidateScopedMixin):
    __tablename__ = "application_documents"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "application_id", "kind", "version", name="uq_application_document"
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
    __table_args__ = (Index("ix_security_events_candidate_time", "candidate_id", "occurred_at"),)

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

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[HumanActionKind] = mapped_column(Enum(HumanActionKind, native_enum=False))
    reason: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Interview(Base, TimestampMixin, CandidateScopedMixin):
    __tablename__ = "interviews"

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

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    decision: Mapped[ReviewDecision] = mapped_column(Enum(ReviewDecision, native_enum=False))
    semantic_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
