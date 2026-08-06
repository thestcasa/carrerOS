from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import ApplicationState, ReviewDecision


class ApplicationContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ApplicationSummary(ApplicationContract):
    application_id: UUID
    candidate_id: str
    job_id: UUID
    company: str
    role: str
    score: int | None
    state: ApplicationState
    last_event: str | None
    updated_at: datetime
    next_action: str


class DocumentView(ApplicationContract):
    document_id: UUID
    kind: str
    version: int
    content: str
    sha256: str
    immutable: bool
    validated: bool
    evidence_ids: tuple[str, ...]
    created_at: datetime
    provenance: tuple[dict[str, object], ...] = ()
    revision_actor: str | None = None
    base_document_id: UUID | None = None
    render_metadata: dict[str, object] = Field(default_factory=dict)


class AnswerView(ApplicationContract):
    answer_id: UUID
    question_key: str
    question: str
    answer: str
    supported: bool
    evidence_ids: tuple[str, ...]


class EventView(ApplicationContract):
    event_id: UUID
    event_type: str
    from_state: ApplicationState
    to_state: ApplicationState
    occurred_at: datetime
    payload: dict[str, object]


class ReviewView(ApplicationContract):
    decision: ReviewDecision
    semantic_passed: bool
    report: dict[str, object]


class CorrespondenceView(ApplicationContract):
    correspondence_id: UUID
    candidate_id: str
    application_id: UUID | None
    provider_message_id: str
    kind: str
    sender: str
    subject: str
    received_at: datetime
    association_reason: str


class CorrespondenceIngestRequest(ApplicationContract):
    candidate_id: str = Field(min_length=1)
    provider_message_id: str = Field(min_length=1)
    thread_id: str | None = None
    sender: str = Field(min_length=1)
    recipients: tuple[str, ...]
    subject: str = Field(min_length=1)
    body_text: str = Field(min_length=1)
    received_at: datetime


class NotificationView(ApplicationContract):
    notification_id: UUID
    candidate_id: str
    application_id: UUID | None
    event_type: str
    channel: str
    message: str
    immediate: bool
    status: str
    created_at: datetime


class ApplicationDetail(ApplicationSummary):
    source_url: str
    ats_platform: str | None
    documents: tuple[DocumentView, ...]
    answers: tuple[AnswerView, ...]
    events: tuple[EventView, ...]
    review: ReviewView | None
    correspondence: tuple[CorrespondenceView, ...]
    archive_available: bool
    confirmation_reference: str | None
    submitted_at: datetime | None


class ArtifactView(ApplicationContract):
    artifact_id: UUID
    application_id: UUID
    candidate_id: str
    kind: str
    version: int
    sha256: str
    content_type: str
    immutable: bool
    download_path: str
    metadata: dict[str, object]
    created_at: datetime


class DryRunCommand(ApplicationContract):
    challenge: Literal["captcha", "otp"] | None = None


class MaterialRevisionRequest(ApplicationContract):
    document_id: UUID
    base_version: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=100_000)
    reason: str | None = Field(default=None, max_length=500)


class AuthorizationView(ApplicationContract):
    authorization_id: UUID
    application_id: UUID
    candidate_id: str
    workflow_state: ApplicationState
    issued_at: datetime
    expires_at: datetime


class SyntheticSubmissionRequest(ApplicationContract):
    authorization_id: UUID
    synthetic_fixture_acknowledged: bool

    @model_validator(mode="after")
    def confirmation_is_consistent(self) -> SyntheticSubmissionRequest:
        if not self.synthetic_fixture_acknowledged:
            raise ValueError("submission execution is restricted to the synthetic fixture")
        return self


class SubmissionResultView(ApplicationContract):
    application_id: UUID
    state: ApplicationState
    successful: bool
    status: Literal["confirmed", "confirmation_missing"]
    confirmation_reference: str | None


class HumanActionView(ApplicationContract):
    action_id: UUID
    candidate_id: str
    application_id: UUID
    company: str
    role: str
    kind: str
    status: Literal["pending", "completed", "cancelled"]
    reason: str | None
    created_at: datetime
    expires_at: datetime | None
    screenshot_available: bool
    browser_session_id: UUID | None
    session_opened: bool


class SecurityEventView(ApplicationContract):
    event_id: UUID
    candidate_id: str
    application_id: UUID | None
    category: str
    severity: str
    details: dict[str, object]
    resolved: bool
    occurred_at: datetime


class SettingsView(ApplicationContract):
    candidate_id: str
    automation_mode: Literal["disabled", "dry_run", "approval_required", "autonomous"]
    discovery_enabled: bool
    emergency_stopped: bool
    allowed_ats_adapters: tuple[str, ...]
    tested_ats_adapters: tuple[str, ...]
    dry_run_acceptance_passed: bool
    explicit_autonomy_confirmation: bool
    maximum_applications_per_day: int
    maximum_applications_per_week: int
    maximum_applications_per_company_30_days: int
    browser_session_retention_days: int
    autonomy_blockers: tuple[str, ...]


class SettingsUpdate(ApplicationContract):
    candidate_id: str = Field(min_length=1)
    automation_mode: Literal["disabled", "dry_run", "approval_required", "autonomous"] | None = None
    discovery_enabled: bool | None = None
    allowed_ats_adapters: tuple[str, ...] | None = None
    tested_ats_adapters: tuple[str, ...] | None = None
    dry_run_acceptance_passed: bool | None = None
    explicit_autonomy_confirmation: bool | None = None
    maximum_applications_per_day: int | None = Field(default=None, ge=1, le=100)
    maximum_applications_per_week: int | None = Field(default=None, ge=1, le=500)
    maximum_applications_per_company_30_days: int | None = Field(default=None, ge=1, le=20)
    browser_session_retention_days: int | None = Field(default=None, ge=1, le=3650)


class AnalyticsOverview(ApplicationContract):
    candidate_id: str
    applications: int
    average_score: float
    by_state: dict[str, int]
    by_role_category: dict[str, int]
    human_actions_pending: int
    security_events_unresolved: int
    confirmations: int
