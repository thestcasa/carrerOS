from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from app.auth.contracts import CandidateDataPlan, DataPlanItem


class CandidateDataPlanner:
    def __init__(self, *, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))

    def export_plan(self, candidate_id: str) -> CandidateDataPlan:
        return CandidateDataPlan(
            operation="export",
            candidate_id=self._candidate_id(candidate_id),
            created_at=self._now().astimezone(UTC),
            items=tuple(
                DataPlanItem(
                    category=category,
                    locator=locator,
                    action="include",
                    reason="Candidate portability export.",
                )
                for category, locator in self._locators(candidate_id)
                if category != "browser_session"
            ),
            warnings=("Secret values are excluded from exports.",),
        )

    def delete_plan(self, candidate_id: str) -> CandidateDataPlan:
        retained = {"audit"}
        return CandidateDataPlan(
            operation="delete",
            candidate_id=self._candidate_id(candidate_id),
            created_at=self._now().astimezone(UTC),
            items=tuple(
                DataPlanItem(
                    category=category,
                    locator=locator,
                    action="retain" if category in retained else "delete",
                    reason="Retained as a non-secret accountability record."
                    if category in retained
                    else "Candidate deletion request.",
                )
                for category, locator in self._locators(candidate_id)
            ),
            warnings=("This is a plan only and performs no deletion.",),
        )

    @staticmethod
    def _candidate_id(value: str) -> str:
        if not value or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in value
        ):
            raise ValueError("candidate_id contains invalid characters")
        return value

    def _locators(self, candidate_id: str) -> tuple[tuple[str, str], ...]:
        safe_id = self._candidate_id(candidate_id)
        return (
            ("configuration", f"candidates/{safe_id}"),
            ("database", f"candidate_id={safe_id}"),
            ("artifacts", f"artifacts/{safe_id}"),
            ("browser_session", f"browser-sessions/{safe_id}"),
            ("audit", f"audit:candidate_id={safe_id}"),
        )
