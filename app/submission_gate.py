from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ApplicationState


class SubmissionGateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    application_id: UUID
    job_still_open: bool | None = None
    official_or_verified_source: bool | None = None
    duplicate_application: bool | None = None
    company_not_blocked: bool | None = None
    role_not_blocked: bool | None = None
    classification_allowed: bool | None = None
    mandatory_requirements_compatible: bool | None = None
    location_compatible: bool | None = None
    language_compatible: bool | None = None
    availability_compatible: bool | None = None
    work_authorization_answer_approved: bool | None = None
    salary_policy_compatible: bool | None = None
    candidate_snapshot_valid: bool | None = None
    cv_render_valid: bool | None = None
    cover_letter_valid: bool | None = None
    answers_valid: bool | None = None
    unsupported_claims_count: int | None = Field(default=None, ge=0)
    unresolved_sensitive_questions_count: int | None = Field(default=None, ge=0)
    prompt_injection_risk_allowed: bool | None = None
    captcha_pending: bool | None = None
    target_domain_validated: bool | None = None
    final_page_matches_job: bool | None = None
    pre_submit_archive_created: bool | None = None
    rate_limits_allowed: bool | None = None
    configuration_valid: bool | None = None
    candidate_score: int | None = Field(default=None, ge=0, le=100)
    application_threshold: int | None = Field(default=None, ge=0, le=100)
    legal_status_approved: bool | None = None
    answers_complete: bool | None = None
    answers_supported: bool | None = None
    documents_valid: bool | None = None
    semantic_review_passed: bool | None = None
    workflow_state: ApplicationState | None = None
    unresolved_security_events: bool | None = None
    human_review_required: bool | None = None
    human_review_approved: bool | None = None


class _AuthorizationIssuer:
    pass


_GATE_ISSUER = _AuthorizationIssuer()
_CLICK_ISSUER = _AuthorizationIssuer()


@dataclass(frozen=True, slots=True, init=False)
class SubmissionAuthorization:
    authorization_id: UUID
    candidate_id: str
    application_id: UUID
    workflow_state: ApplicationState
    issued_at: datetime
    expires_at: datetime

    def __init__(
        self,
        *,
        issuer: Any,
        candidate_id: str,
        application_id: UUID,
        workflow_state: ApplicationState,
        issued_at: datetime,
        expires_at: datetime,
    ) -> None:
        if issuer is not _GATE_ISSUER:
            raise PermissionError("only SubmissionGate may issue submission authorization")
        object.__setattr__(self, "authorization_id", uuid4())
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "application_id", application_id)
        object.__setattr__(self, "workflow_state", workflow_state)
        object.__setattr__(self, "issued_at", issued_at)
        object.__setattr__(self, "expires_at", expires_at)


@dataclass(frozen=True, slots=True)
class GateDecision:
    permitted: bool
    reasons: tuple[str, ...]
    authorization: SubmissionAuthorization | None


class FinalClickPermit:
    """Ephemeral, one-use capability that is never persisted or serialized."""

    __slots__ = (
        "_consumed",
        "application_id",
        "attempt_id",
        "authorization_id",
        "candidate_id",
        "expires_at",
    )

    def __init__(
        self,
        *,
        issuer: Any,
        candidate_id: str,
        application_id: UUID,
        authorization_id: UUID,
        attempt_id: UUID,
        expires_at: datetime,
    ) -> None:
        if issuer is not _CLICK_ISSUER:
            raise PermissionError("only SubmissionGate may issue a final click permit")
        self.candidate_id = candidate_id
        self.application_id = application_id
        self.authorization_id = authorization_id
        self.attempt_id = attempt_id
        self.expires_at = expires_at
        self._consumed = False

    def consume(
        self,
        *,
        candidate_id: str,
        application_id: UUID,
        authorization_id: UUID,
        attempt_id: UUID,
    ) -> None:
        if self._consumed:
            raise PermissionError("final click permit was already consumed")
        if datetime.now(UTC) >= self.expires_at:
            raise PermissionError("final click permit expired")
        if (
            self.candidate_id != candidate_id
            or self.application_id != application_id
            or self.authorization_id != authorization_id
            or self.attempt_id != attempt_id
        ):
            raise PermissionError("final click permit scope does not match the request")
        self._consumed = True


@dataclass(frozen=True, slots=True)
class FinalClickProof:
    candidate_id: str
    application_id: UUID
    authorization_id: UUID
    attempt_id: UUID
    application_state: ApplicationState
    attempt_status: str
    authorization_consumed_at: datetime | None
    click_boundary_entered_at: datetime | None
    click_nonce_sha256: str | None


class SubmissionGate:
    def __init__(self, authorization_ttl: timedelta = timedelta(minutes=10)) -> None:
        if authorization_ttl <= timedelta(0):
            raise ValueError("authorization_ttl must be positive")
        self._authorization_ttl = authorization_ttl

    def evaluate(self, gate_input: SubmissionGateInput) -> GateDecision:
        reasons: list[str] = []
        required_flags = {
            "configuration_invalid_or_missing": gate_input.configuration_valid,
            "job_closed_or_missing": gate_input.job_still_open,
            "source_unverified_or_missing": gate_input.official_or_verified_source,
            "company_blocked_or_missing": gate_input.company_not_blocked,
            "role_blocked_or_missing": gate_input.role_not_blocked,
            "classification_disallowed_or_missing": gate_input.classification_allowed,
            "mandatory_requirements_incompatible_or_missing": (
                gate_input.mandatory_requirements_compatible
            ),
            "location_incompatible_or_missing": gate_input.location_compatible,
            "language_incompatible_or_missing": gate_input.language_compatible,
            "availability_incompatible_or_missing": gate_input.availability_compatible,
            "legal_status_unapproved_or_missing": gate_input.legal_status_approved,
            "work_authorization_answer_unapproved_or_missing": (
                gate_input.work_authorization_answer_approved
            ),
            "salary_policy_incompatible_or_missing": gate_input.salary_policy_compatible,
            "candidate_snapshot_invalid_or_missing": gate_input.candidate_snapshot_valid,
            "cv_render_invalid_or_missing": gate_input.cv_render_valid,
            "cover_letter_invalid_or_missing": gate_input.cover_letter_valid,
            "answers_invalid_or_missing": gate_input.answers_valid,
            "answers_incomplete_or_missing": gate_input.answers_complete,
            "answers_unsupported_or_missing": gate_input.answers_supported,
            "documents_invalid_or_missing": gate_input.documents_valid,
            "semantic_review_failed_or_missing": gate_input.semantic_review_passed,
            "prompt_injection_risk_unapproved_or_missing": gate_input.prompt_injection_risk_allowed,
            "target_domain_invalid_or_missing": gate_input.target_domain_validated,
            "final_page_mismatch_or_missing": gate_input.final_page_matches_job,
            "pre_submit_archive_missing": gate_input.pre_submit_archive_created,
            "rate_limit_reached_or_missing": gate_input.rate_limits_allowed,
        }
        reasons.extend(code for code, value in required_flags.items() if value is not True)

        if gate_input.duplicate_application is not False:
            reasons.append("duplicate_application_detected_or_missing")
        if gate_input.captcha_pending is not False:
            reasons.append("captcha_pending_or_missing")
        if gate_input.unsupported_claims_count is None:
            reasons.append("unsupported_claims_count_missing")
        elif gate_input.unsupported_claims_count != 0:
            reasons.append("unsupported_claims_present")
        if gate_input.unresolved_sensitive_questions_count is None:
            reasons.append("sensitive_question_count_missing")
        elif gate_input.unresolved_sensitive_questions_count != 0:
            reasons.append("unresolved_sensitive_questions_present")

        if gate_input.candidate_score is None or gate_input.application_threshold is None:
            reasons.append("score_or_threshold_missing")
        elif gate_input.candidate_score < gate_input.application_threshold:
            reasons.append("candidate_score_below_threshold")

        if gate_input.workflow_state is not ApplicationState.READY_TO_SUBMIT:
            reasons.append("workflow_not_ready")
        if gate_input.unresolved_security_events is not False:
            reasons.append("security_status_unresolved_or_missing")
        if gate_input.human_review_required is None:
            reasons.append("human_review_requirement_missing")
        elif gate_input.human_review_required and gate_input.human_review_approved is not True:
            reasons.append("human_review_not_approved")

        if reasons:
            return GateDecision(permitted=False, reasons=tuple(reasons), authorization=None)

        now = datetime.now(UTC)
        authorization = SubmissionAuthorization(
            issuer=_GATE_ISSUER,
            candidate_id=gate_input.candidate_id,
            application_id=gate_input.application_id,
            workflow_state=ApplicationState.READY_TO_SUBMIT,
            issued_at=now,
            expires_at=now + self._authorization_ttl,
        )
        return GateDecision(permitted=True, reasons=(), authorization=authorization)

    def issue_final_click_permit(
        self,
        proof: FinalClickProof,
        click_nonce: bytes,
        *,
        permit_ttl: timedelta = timedelta(seconds=30),
    ) -> FinalClickPermit:
        """Issue only from a committed, consumed, click-armed durable proof."""

        if permit_ttl <= timedelta(0) or permit_ttl > timedelta(minutes=1):
            raise ValueError("final click permit TTL must be positive and at most one minute")
        if len(click_nonce) != 32:
            raise PermissionError("final click nonce is invalid")
        nonce_sha256 = hashlib.sha256(click_nonce).hexdigest()
        if (
            proof.application_state is not ApplicationState.SUBMITTING
            or proof.attempt_status != "click_authorized"
            or proof.authorization_consumed_at is None
            or proof.click_boundary_entered_at is None
            or proof.click_nonce_sha256 is None
            or not hmac.compare_digest(proof.click_nonce_sha256, nonce_sha256)
        ):
            raise PermissionError("durable click authorization proof is invalid")
        return FinalClickPermit(
            issuer=_CLICK_ISSUER,
            candidate_id=proof.candidate_id,
            application_id=proof.application_id,
            authorization_id=proof.authorization_id,
            attempt_id=proof.attempt_id,
            expires_at=datetime.now(UTC) + permit_ttl,
        )
