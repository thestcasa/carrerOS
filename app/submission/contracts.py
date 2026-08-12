from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import ApplicationState
from app.submission_gate import FinalClickPermit


class SubmissionContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GreenhouseFormInspection(SubmissionContract):
    target_url: str = Field(min_length=1, max_length=2048)
    form_action: str = Field(min_length=1, max_length=2048)
    form_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    required_selectors: tuple[str, ...]
    submit_selector: str
    submit_control_count: Literal[1]
    human_verification_present: Literal[False]


class ControlledAuthorizationRequest(SubmissionContract):
    approval_acknowledged: bool
    consequence_version: Literal["controlled-approval-consequences-v1"]

    @model_validator(mode="after")
    def approval_is_explicit(self) -> ControlledAuthorizationRequest:
        if not self.approval_acknowledged:
            raise ValueError("controlled submission requires explicit approval")
        return self


class ControlledSubmissionCommand(SubmissionContract):
    authorization_id: UUID


class ControlledGreenhouseFormPayload(SubmissionContract):
    """Exact reviewed values that the controlled adapter may place on its tested form."""

    first_name: str = Field(min_length=1, max_length=200)
    last_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    resume_path: Path
    resume_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    def sha256(self) -> str:
        payload = {
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "resume_sha256": self.resume_sha256,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class ControlledSubmissionPreparationRequest(SubmissionContract):
    attempt_id: UUID
    candidate_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    application_id: UUID
    authorization_id: UUID
    browser_session_id: UUID
    target_url: str = Field(min_length=1, max_length=2048)
    form: ControlledGreenhouseFormPayload


class PreparedControlledSubmission(SubmissionContract):
    attempt_id: UUID
    inspection: GreenhouseFormInspection
    form_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    pre_click_screenshot_png: bytes = Field(min_length=8, max_length=16 * 1024 * 1024)
    pre_click_page_html: bytes = Field(min_length=1, max_length=4 * 1024 * 1024)


class ControlledSubmissionRequest(SubmissionContract):
    attempt_id: UUID
    candidate_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    application_id: UUID
    authorization_id: UUID
    target_url: str = Field(min_length=1, max_length=2048)
    package_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    form: ControlledGreenhouseFormPayload
    expected_form_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_form_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class ControlledSubmissionResult(SubmissionContract):
    attempt_id: UUID
    click_invoked: Literal[True]
    confirmation_detected: bool
    confirmation_reference: str | None = Field(default=None, max_length=255)
    final_url: str = Field(min_length=1, max_length=2048)
    screenshot_png: bytes = Field(min_length=8, max_length=16 * 1024 * 1024)
    final_page_html: bytes = Field(min_length=1, max_length=4 * 1024 * 1024)

    @model_validator(mode="after")
    def confirmation_has_reference(self) -> ControlledSubmissionResult:
        if self.confirmation_detected != (self.confirmation_reference is not None):
            raise ValueError("confirmation evidence and reference must agree")
        return self


class ControlledSubmissionExecutionView(SubmissionContract):
    attempt_id: UUID
    application_id: UUID
    candidate_id: str
    authorization_id: UUID
    task_id: UUID | None
    adapter: Literal["greenhouse_controlled_v1"]
    status: Literal[
        "prepared",
        "click_authorized",
        "confirmed",
        "confirmation_missing",
        "unknown_after_click",
        "denied",
    ]
    application_state: ApplicationState
    successful: bool
    retryable: Literal[False] = False
    confirmation_reference: str | None
    click_boundary_entered_at: datetime | None
    finalized_at: datetime | None


class ControlledSubmissionExecutor(Protocol):
    def prepare(
        self, request: ControlledSubmissionPreparationRequest
    ) -> PreparedControlledSubmission: ...

    def execute(
        self,
        request: ControlledSubmissionRequest,
        permit: FinalClickPermit,
    ) -> ControlledSubmissionResult: ...

    def abort(self) -> None: ...


class ControlledSubmissionError(RuntimeError):
    """Final submission was safely denied before the click boundary."""

    def __init__(
        self,
        message: str,
        *,
        category: str = "controlled_validation",
        human_action_kind: Literal["captcha", "otp", "novel_required_field"] | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.human_action_kind = human_action_kind


class ControlledSubmissionUncertainError(RuntimeError):
    """The click may have occurred; automated retry is forbidden."""

    def __init__(self, message: str, *, click_may_have_occurred: Literal[True] = True) -> None:
        super().__init__(message)
        self.click_may_have_occurred = click_may_have_occurred
