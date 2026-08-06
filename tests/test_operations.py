from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.domain.enums import ApplicationState
from app.domain.models import Application, Base, GlobalJob
from app.operations import (
    AnalyticsService,
    ApplicationMetric,
    AuthorizationConsumer,
    AuthorizationConsumptionError,
    AutomationGuard,
    AutomationMode,
    AutomationReadiness,
    BackendSubmissionEvidence,
    DigestService,
    EmergencyStop,
    NotificationService,
    RateLimiter,
    RateLimitPolicy,
    confirmed_outcome,
)
from app.operations.policy import OperationsPolicyError
from app.submission_gate import SubmissionAuthorization, SubmissionGate, SubmissionGateInput


def _authorization() -> tuple[SubmissionAuthorization, SubmissionGateInput]:
    gate_input = SubmissionGateInput(
        candidate_id="candidate_alpha",
        application_id=uuid4(),
        job_still_open=True,
        official_or_verified_source=True,
        duplicate_application=False,
        company_not_blocked=True,
        role_not_blocked=True,
        classification_allowed=True,
        mandatory_requirements_compatible=True,
        location_compatible=True,
        language_compatible=True,
        availability_compatible=True,
        work_authorization_answer_approved=True,
        salary_policy_compatible=True,
        candidate_snapshot_valid=True,
        cv_render_valid=True,
        cover_letter_valid=True,
        answers_valid=True,
        unsupported_claims_count=0,
        unresolved_sensitive_questions_count=0,
        prompt_injection_risk_allowed=True,
        captcha_pending=False,
        target_domain_validated=True,
        final_page_matches_job=True,
        pre_submit_archive_created=True,
        rate_limits_allowed=True,
        configuration_valid=True,
        candidate_score=90,
        application_threshold=80,
        legal_status_approved=True,
        answers_complete=True,
        answers_supported=True,
        documents_valid=True,
        semantic_review_passed=True,
        workflow_state=ApplicationState.READY_TO_SUBMIT,
        unresolved_security_events=False,
        human_review_required=False,
    )
    decision = SubmissionGate(authorization_ttl=timedelta(minutes=1)).evaluate(gate_input)
    assert decision.authorization is not None
    return decision.authorization, gate_input


def _authorization_sessions(gate_input: SubmissionGateInput) -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        job = GlobalJob(
            source="synthetic",
            external_id=str(uuid4()),
            company="Fictional Labs",
            title="Synthetic role",
            description="Synthetic fixture",
            url="https://jobs.example.invalid/synthetic",
        )
        session.add(job)
        session.flush()
        session.add(
            Application(
                id=gate_input.application_id,
                candidate_id=gate_input.candidate_id,
                job_id=job.id,
                duplicate_hash="0" * 64,
                submission_identity_hash="1" * 64,
                state=ApplicationState.READY_TO_SUBMIT,
            )
        )
    return factory


def test_gate_authorization_is_bound_short_lived_and_consumed_once() -> None:
    authorization, gate_input = _authorization()
    sessions = _authorization_sessions(gate_input)
    consumer = AuthorizationConsumer(sessions)

    assert (
        consumer.consume(
            authorization,
            candidate_id=gate_input.candidate_id,
            application_id=gate_input.application_id,
            now=authorization.issued_at,
        )
        == authorization.authorization_id
    )
    with pytest.raises(AuthorizationConsumptionError, match="already consumed"):
        consumer.consume(
            authorization,
            candidate_id=gate_input.candidate_id,
            application_id=gate_input.application_id,
            now=authorization.issued_at,
        )
    with pytest.raises(AuthorizationConsumptionError, match="already consumed"):
        AuthorizationConsumer(sessions).consume(
            authorization,
            candidate_id=gate_input.candidate_id,
            application_id=gate_input.application_id,
            now=authorization.issued_at,
        )


def test_authorization_rejects_wrong_binding_and_expiry() -> None:
    authorization, gate_input = _authorization()
    consumer = AuthorizationConsumer(_authorization_sessions(gate_input))
    with pytest.raises(AuthorizationConsumptionError, match="candidate binding"):
        consumer.consume(
            authorization,
            candidate_id="candidate_beta",
            application_id=gate_input.application_id,
            now=authorization.issued_at,
        )
    with pytest.raises(AuthorizationConsumptionError, match="not currently valid"):
        consumer.consume(
            authorization,
            candidate_id=gate_input.candidate_id,
            application_id=gate_input.application_id,
            now=authorization.expires_at,
        )


def test_authorization_is_bound_to_persisted_ready_state() -> None:
    authorization, gate_input = _authorization()
    sessions = _authorization_sessions(gate_input)
    with sessions.begin() as session:
        application = session.get(Application, gate_input.application_id)
        assert application is not None
        application.state = ApplicationState.SUBMITTING

    with pytest.raises(AuthorizationConsumptionError, match="persisted workflow state"):
        AuthorizationConsumer(sessions).consume(
            authorization,
            candidate_id=gate_input.candidate_id,
            application_id=gate_input.application_id,
            now=authorization.issued_at,
        )


def test_emergency_stop_and_rate_limits_fail_closed_per_candidate() -> None:
    stop = EmergencyStop()
    stop.activate("candidate_alpha")
    with pytest.raises(OperationsPolicyError, match="emergency stop"):
        stop.assert_allows_new_submission("candidate_alpha")
    stop.assert_allows_new_submission("candidate_beta")

    limiter = RateLimiter(RateLimitPolicy(2, 3, 1))
    now = datetime(2026, 8, 4, 10, tzinfo=UTC)
    limiter.record("candidate_alpha", "Fictional Labs", now)
    with pytest.raises(OperationsPolicyError, match="per-company"):
        limiter.record("candidate_alpha", "fictional labs", now + timedelta(minutes=1))
    limiter.record("candidate_beta", "Fictional Labs", now + timedelta(minutes=1))


def test_autonomous_mode_requires_every_readiness_guard() -> None:
    readiness = AutomationReadiness(
        candidate_id="candidate_alpha",
        configuration_ready=True,
        legal_answers_approved=True,
        tested_ats_adapters=frozenset({"greenhouse"}),
        dry_run_acceptance_passed=True,
        explicit_confirmation=False,
    )
    with pytest.raises(OperationsPolicyError, match="explicit confirmation"):
        AutomationGuard().assert_mode_allowed(AutomationMode.AUTONOMOUS, readiness, "greenhouse")
    AutomationGuard().assert_mode_allowed(AutomationMode.APPROVAL_REQUIRED, readiness, "ashby")
    AutomationGuard().assert_mode_allowed(
        AutomationMode.AUTONOMOUS,
        readiness.model_copy(update={"explicit_confirmation": True}),
        "greenhouse",
    )


def test_submission_success_requires_backend_confirmation_and_receipt() -> None:
    attempted = BackendSubmissionEvidence(
        application_id=uuid4(),
        candidate_id="candidate_alpha",
        attempted_at=datetime(2026, 8, 4, tzinfo=UTC),
        backend_confirmation_detected=False,
    )
    outcome = confirmed_outcome(attempted)
    assert not outcome.successful
    assert outcome.status == "confirmation_missing"

    with pytest.raises(ValidationError, match="requires a reference"):
        attempted.model_copy(update={"backend_confirmation_detected": True}).model_validate(
            {
                **attempted.model_dump(),
                "backend_confirmation_detected": True,
            }
        )
    confirmed = BackendSubmissionEvidence(
        application_id=attempted.application_id,
        candidate_id=attempted.candidate_id,
        attempted_at=attempted.attempted_at,
        backend_confirmation_detected=True,
        confirmation_reference="synthetic-confirmation-1",
        receipt_sha256="a" * 64,
    )
    assert confirmed_outcome(confirmed).successful


def test_notifications_digest_and_analytics_are_candidate_neutral_projections() -> None:
    notifier = NotificationService()
    now = datetime(2026, 8, 4, tzinfo=UTC)
    events = (
        notifier.build(
            candidate_id="candidate_alpha",
            event_type="captcha",
            occurred_at=now,
            message="Human action",
        ),
        notifier.build(
            candidate_id="candidate_alpha",
            event_type="submitted",
            occurred_at=now,
            message="Synthetic submission",
        ),
    )
    assert events[0].immediate
    assert not events[1].immediate
    assert DigestService().summarize(events) == {"captcha": 1, "submitted": 1}

    metrics = (
        ApplicationMetric(
            candidate_id="candidate_alpha",
            application_id=uuid4(),
            company="Fictional Labs",
            role_category="ai_ml_core",
            ats_platform="greenhouse",
            score=90,
            state="confirmed",
            human_interventions=1,
        ),
        ApplicationMetric(
            candidate_id="candidate_alpha",
            application_id=uuid4(),
            company="Example Systems",
            role_category="ai_ml_adjacent",
            ats_platform="lever",
            score=70,
            state="shortlisted",
            human_interventions=0,
        ),
    )
    overview = AnalyticsService().overview(metrics)
    assert overview["applications"] == 2
    assert overview["average_score"] == 80.0
    assert overview["by_role_category"] == {"ai_ml_adjacent": 1, "ai_ml_core": 1}
