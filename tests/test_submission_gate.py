from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.domain.enums import ApplicationState
from app.submission_gate import SubmissionAuthorization, SubmissionGate, SubmissionGateInput


def _passing_input(**overrides: object) -> SubmissionGateInput:
    values: dict[str, object] = {
        "candidate_id": "candidate_alpha",
        "application_id": uuid4(),
        "job_still_open": True,
        "official_or_verified_source": True,
        "duplicate_application": False,
        "company_not_blocked": True,
        "role_not_blocked": True,
        "classification_allowed": True,
        "mandatory_requirements_compatible": True,
        "location_compatible": True,
        "language_compatible": True,
        "availability_compatible": True,
        "work_authorization_answer_approved": True,
        "salary_policy_compatible": True,
        "candidate_snapshot_valid": True,
        "cv_render_valid": True,
        "cover_letter_valid": True,
        "answers_valid": True,
        "unsupported_claims_count": 0,
        "unresolved_sensitive_questions_count": 0,
        "prompt_injection_risk_allowed": True,
        "captcha_pending": False,
        "target_domain_validated": True,
        "final_page_matches_job": True,
        "pre_submit_archive_created": True,
        "configuration_valid": True,
        "candidate_score": 85,
        "application_threshold": 80,
        "legal_status_approved": True,
        "answers_complete": True,
        "answers_supported": True,
        "documents_valid": True,
        "semantic_review_passed": True,
        "workflow_state": ApplicationState.READY_TO_SUBMIT,
        "unresolved_security_events": False,
        "human_review_required": False,
        "human_review_approved": None,
    }
    values.update(overrides)
    return SubmissionGateInput.model_validate(values)


def test_submission_is_denied_when_fields_are_missing() -> None:
    gate_input = SubmissionGateInput(candidate_id="candidate_alpha", application_id=uuid4())
    decision = SubmissionGate().evaluate(gate_input)

    assert decision.permitted is False
    assert decision.authorization is None
    assert "score_or_threshold_missing" in decision.reasons
    assert "semantic_review_failed_or_missing" in decision.reasons


def test_submission_is_denied_for_unapproved_legal_status() -> None:
    decision = SubmissionGate().evaluate(_passing_input(legal_status_approved=False))

    assert decision.permitted is False
    assert "legal_status_unapproved_or_missing" in decision.reasons


def test_submission_is_denied_after_semantic_review_failure() -> None:
    decision = SubmissionGate().evaluate(_passing_input(semantic_review_passed=False))

    assert decision.permitted is False
    assert "semantic_review_failed_or_missing" in decision.reasons


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"duplicate_application": True}, "duplicate_application_detected_or_missing"),
        ({"duplicate_application": None}, "duplicate_application_detected_or_missing"),
        ({"captcha_pending": True}, "captcha_pending_or_missing"),
        ({"captcha_pending": None}, "captcha_pending_or_missing"),
        ({"unsupported_claims_count": 1}, "unsupported_claims_present"),
        ({"unsupported_claims_count": None}, "unsupported_claims_count_missing"),
        (
            {"unresolved_sensitive_questions_count": 1},
            "unresolved_sensitive_questions_present",
        ),
        ({"unresolved_sensitive_questions_count": None}, "sensitive_question_count_missing"),
    ],
)
def test_submission_is_denied_for_zero_tolerance_safety_failures(
    override: dict[str, object], reason: str
) -> None:
    decision = SubmissionGate().evaluate(_passing_input(**override))

    assert decision.permitted is False
    assert decision.authorization is None
    assert reason in decision.reasons


def test_gate_issues_bound_short_lived_authorization_only_on_success() -> None:
    gate_input = _passing_input()
    decision = SubmissionGate(authorization_ttl=timedelta(minutes=2)).evaluate(gate_input)

    assert decision.permitted is True
    assert decision.authorization is not None
    assert decision.authorization.candidate_id == gate_input.candidate_id
    assert decision.authorization.application_id == gate_input.application_id
    assert decision.authorization.expires_at > decision.authorization.issued_at


def test_authorization_cannot_be_constructed_outside_gate() -> None:
    now = datetime.now(UTC)
    with pytest.raises(PermissionError):
        SubmissionAuthorization(
            issuer=object(),
            candidate_id="candidate_alpha",
            application_id=uuid4(),
            workflow_state=ApplicationState.READY_TO_SUBMIT,
            issued_at=now,
            expires_at=now + timedelta(minutes=1),
        )
