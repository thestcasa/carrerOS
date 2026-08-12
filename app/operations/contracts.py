from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OperationsContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AutomationMode(StrEnum):
    DISABLED = "disabled"
    DRY_RUN = "dry_run"
    APPROVAL_REQUIRED = "approval_required"
    AUTONOMOUS = "autonomous"


class AutomationReadiness(OperationsContract):
    candidate_id: str = Field(min_length=1)
    configuration_ready: bool
    legal_answers_approved: bool
    tested_ats_adapters: frozenset[str]
    dry_run_acceptance_passed: bool
    explicit_confirmation: bool


class BackendSubmissionEvidence(OperationsContract):
    application_id: UUID
    candidate_id: str = Field(min_length=1)
    attempted_at: datetime
    backend_confirmation_detected: bool
    confirmation_reference: str | None = None
    receipt_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def confirmation_requires_evidence(self) -> BackendSubmissionEvidence:
        if self.backend_confirmation_detected and not (
            self.confirmation_reference and self.receipt_sha256
        ):
            raise ValueError("backend confirmation requires a reference and receipt hash")
        return self


class SubmissionOutcome(OperationsContract):
    application_id: UUID
    candidate_id: str
    status: Literal["confirmation_missing", "confirmed"]
    successful: bool
    confirmation_reference: str | None
    receipt_sha256: str | None


class NotificationEvent(OperationsContract):
    candidate_id: str
    event_type: str = Field(min_length=1)
    occurred_at: datetime
    message: str = Field(min_length=1)
    immediate: bool


class ApplicationMetric(OperationsContract):
    candidate_id: str
    application_id: UUID
    company: str
    role_category: str
    ats_platform: str
    score: int = Field(ge=0, le=100)
    state: str
    submitted_at: datetime | None = None
    human_interventions: int = Field(ge=0)
