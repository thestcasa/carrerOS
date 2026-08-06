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
    version: int
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    immutable: bool
    revision_kind: Literal["generated", "manual", "withdrawn", "legacy_unknown"]
    revision_actor: str
    base_answer_id: UUID | None
    reason: str | None
    approved_source_key: str | None
    candidate_snapshot_id: UUID | None
    candidate_snapshot_version: str | None
    candidate_snapshot_sha256: str | None
    supported: bool
    evidence_ids: tuple[str, ...]
    created_at: datetime


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


class CoverLetterMaterialPolicy(ApplicationContract):
    included: bool
    reason: str | None
    selected_experience_ids: tuple[str, ...]
    selected_project_ids: tuple[str, ...]
    minimum_words: int = Field(ge=50, le=250)
    maximum_words: int = Field(ge=50, le=2000)

    @model_validator(mode="after")
    def word_range_is_valid(self) -> CoverLetterMaterialPolicy:
        if self.maximum_words < self.minimum_words:
            raise ValueError("cover-letter maximum words must be at least minimum words")
        if self.included != (self.reason is not None):
            raise ValueError("cover-letter inclusion must have one explicit reason")
        return self


class ApplicationMaterialPolicy(ApplicationContract):
    schema_version: Literal["1.0"] = "1.0"
    generator_version: Literal["deterministic_material_v2", "legacy_material_unknown"]
    job_version: int = Field(ge=1)
    job_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    cv_template_id: Literal["technical_single_page", "technical_two_page", "legacy-configured"]
    cv_template_version: Literal["1.0", "unknown"]
    selected_experience_ids: tuple[str, ...]
    selected_project_ids: tuple[str, ...]
    cover_letter: CoverLetterMaterialPolicy


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
    material_policy: ApplicationMaterialPolicy | None = None


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


class AnswerRevisionRequest(ApplicationContract):
    answer_id: UUID
    base_version: int = Field(ge=1)
    answer: str = Field(min_length=1, max_length=10_000)
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def answer_is_not_blank(self) -> AnswerRevisionRequest:
        if not self.answer.strip():
            raise ValueError("answer revision must contain non-whitespace text")
        return self


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
    screenshot_artifact_id: UUID | None = None
    screenshot_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    screenshot_download_path: str | None = None
    browser_session_id: UUID | None
    session_opened: bool
    browser_session_health: Literal[
        "unavailable",
        "paused",
        "takeover_opened",
        "resuming",
        "ready",
        "failed",
        "closed",
        "expired",
    ] = "unavailable"
    safe_origin: str | None = None
    takeover_capability_status: Literal["unavailable", "not_required"] = "unavailable"
    takeover_handshake_status: Literal[
        "unavailable", "ready_to_open", "opened", "closed", "expired", "not_required"
    ] = "unavailable"
    verifier_state: Literal[
        "not_required",
        "awaiting_human",
        "awaiting_browser_verification",
        "verified",
        "cancelled",
        "expired",
        "unavailable",
    ] = "unavailable"
    continue_available: bool = False
    cancel_available: bool = False
    continue_consequence: str = (
        "Career OS requires backend validation before any workflow can continue."
    )
    cancel_consequence: str = (
        "Career OS cancels this workflow and withdraws the application; no submission is attempted."
    )


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
