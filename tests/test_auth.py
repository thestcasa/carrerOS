from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.auth.audit import AdminAuditLog
from app.auth.planning import CandidateDataPlanner
from app.auth.rate_limit import FixedWindowRateLimiter
from app.auth.tokens import LocalTokenService, TokenValidationError


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


def _tokens(clock: Clock) -> LocalTokenService:
    return LocalTokenService(b"fictional-local-secret-that-is-at-least-32-bytes", now=clock)


def test_session_is_signed_expiring_and_candidate_scoped() -> None:
    clock = Clock()
    service = _tokens(clock)
    token = service.issue_session(
        session_id="session-123",
        user_id="user-1",
        candidate_ids=("candidate_b", "candidate_a"),
        lifetime=timedelta(minutes=5),
    )
    claims = service.verify_session(token)

    assert claims.candidate_ids == ("candidate_a", "candidate_b")
    service.require_candidate(claims, "candidate_a")
    with pytest.raises(PermissionError):
        service.require_candidate(claims, "candidate_c")
    with pytest.raises(TokenValidationError):
        service.verify_session(token[:-1] + ("a" if token[-1] != "a" else "b"))
    clock.value += timedelta(minutes=5)
    with pytest.raises(TokenValidationError, match="expired"):
        service.verify_session(token)


def test_csrf_and_artifact_tokens_are_bound_to_exact_scope() -> None:
    clock = Clock()
    service = _tokens(clock)
    csrf = service.issue_csrf(session_id="session-123", lifetime=timedelta(minutes=2))
    service.verify_csrf(csrf, session_id="session-123")
    with pytest.raises(TokenValidationError, match="session"):
        service.verify_csrf(csrf, session_id="session-999")

    artifact = service.issue_artifact_access(
        user_id="user-1",
        candidate_id="candidate_a",
        artifact_path="applications/app-1/cv.pdf",
        lifetime=timedelta(minutes=2),
    )
    service.verify_artifact_access(
        artifact,
        user_id="user-1",
        candidate_id="candidate_a",
        artifact_path="applications/app-1/cv.pdf",
    )
    with pytest.raises(TokenValidationError, match="scope"):
        service.verify_artifact_access(
            artifact,
            user_id="user-1",
            candidate_id="candidate_a",
            artifact_path="applications/app-2/cv.pdf",
        )
    with pytest.raises(ValueError, match="normalized"):
        service.issue_artifact_access(
            user_id="user-1",
            candidate_id="candidate_a",
            artifact_path="../secret",
            lifetime=timedelta(minutes=2),
        )


def test_fixed_window_rate_limit_resets_deterministically() -> None:
    clock = Clock()
    limiter = FixedWindowRateLimiter(limit=2, window=timedelta(minutes=1), now=clock)

    assert limiter.check("user-1").allowed
    second = limiter.check("user-1")
    assert second.allowed and second.remaining == 0
    assert not limiter.check("user-1").allowed
    assert limiter.check("user-2").allowed
    clock.value += timedelta(minutes=1)
    assert limiter.check("user-1").allowed


def test_admin_audit_is_append_only_hash_chained() -> None:
    clock = Clock()
    audit = AdminAuditLog(now=clock)
    first = audit.record(
        admin_user_id="admin-1", action="candidate.export_planned", candidate_id="candidate_a"
    )
    second = audit.record(
        admin_user_id="admin-1",
        action="candidate.delete_planned",
        candidate_id="candidate_a",
        details=(("ticket", "fictional-42"),),
    )

    assert second.previous_hash == first.event_hash
    assert audit.events() == (first, second)
    assert audit.verify()


def test_export_and_delete_plans_never_execute_and_preserve_audit() -> None:
    clock = Clock()
    planner = CandidateDataPlanner(now=clock)
    export = planner.export_plan("candidate_a")
    deletion = planner.delete_plan("candidate_a")

    assert not export.executable and not deletion.executable
    assert {item.action for item in export.items} == {"include"}
    assert next(item for item in deletion.items if item.category == "audit").action == "retain"
    assert next(item for item in deletion.items if item.category == "artifacts").action == "delete"
    assert "performs no deletion" in deletion.warnings[0]
    with pytest.raises(ValueError, match="candidate_id"):
        planner.delete_plan("../escape")
