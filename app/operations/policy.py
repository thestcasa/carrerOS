from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from threading import Lock

from app.operations.contracts import AutomationMode, AutomationReadiness


class OperationsPolicyError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    maximum_daily: int
    maximum_weekly: int
    maximum_per_company_weekly: int

    def __post_init__(self) -> None:
        if min(self.maximum_daily, self.maximum_weekly, self.maximum_per_company_weekly) < 1:
            raise ValueError("rate limits must be positive")


class EmergencyStop:
    def __init__(self) -> None:
        self._stopped_candidates: set[str] = set()
        self._lock = Lock()

    def activate(self, candidate_id: str) -> None:
        with self._lock:
            self._stopped_candidates.add(candidate_id)

    def clear(self, candidate_id: str) -> None:
        with self._lock:
            self._stopped_candidates.discard(candidate_id)

    def assert_allows_new_submission(self, candidate_id: str) -> None:
        with self._lock:
            if candidate_id in self._stopped_candidates:
                raise OperationsPolicyError("emergency stop prevents new submissions")


class AutomationGuard:
    def assert_mode_allowed(
        self, mode: AutomationMode, readiness: AutomationReadiness, allowed_adapter: str
    ) -> None:
        if mode != AutomationMode.AUTONOMOUS:
            return
        checks = {
            "configuration readiness": readiness.configuration_ready,
            "approved legal answers": readiness.legal_answers_approved,
            "tested ATS adapter": allowed_adapter in readiness.tested_ats_adapters,
            "dry-run acceptance": readiness.dry_run_acceptance_passed,
            "explicit confirmation": readiness.explicit_confirmation,
        }
        missing = tuple(name for name, passed in checks.items() if not passed)
        if missing:
            raise OperationsPolicyError(f"autonomous mode blocked by: {', '.join(missing)}")


class RateLimiter:
    def __init__(self, policy: RateLimitPolicy) -> None:
        self._policy = policy
        self._events: list[tuple[str, str, datetime]] = []
        self._lock = Lock()

    def record(self, candidate_id: str, company: str, occurred_at: datetime) -> None:
        if occurred_at.tzinfo is None:
            raise ValueError("rate-limit event time must be timezone-aware")
        normalized_company = company.casefold().strip()
        with self._lock:
            self._assert_within_limits(candidate_id, normalized_company, occurred_at)
            self._events.append((candidate_id, normalized_company, occurred_at))

    def _assert_within_limits(self, candidate_id: str, company: str, occurred_at: datetime) -> None:
        local_day: date = occurred_at.astimezone(UTC).date()
        week_start = occurred_at - timedelta(days=7)
        daily = 0
        weekly: Counter[str] = Counter()
        for event_candidate, event_company, event_time in self._events:
            if event_candidate != candidate_id:
                continue
            if event_time.astimezone(UTC).date() == local_day:
                daily += 1
            if event_time > week_start:
                weekly[event_company] += 1
        if daily >= self._policy.maximum_daily:
            raise OperationsPolicyError("candidate daily application limit reached")
        if weekly.total() >= self._policy.maximum_weekly:
            raise OperationsPolicyError("candidate weekly application limit reached")
        if weekly[company] >= self._policy.maximum_per_company_weekly:
            raise OperationsPolicyError("candidate per-company weekly limit reached")
