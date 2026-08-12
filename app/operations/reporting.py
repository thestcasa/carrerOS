from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime

from app.operations.contracts import ApplicationMetric, NotificationEvent

_IMMEDIATE_EVENTS = frozenset(
    {
        "captcha",
        "otp",
        "security_alert",
        "failed_submission",
        "interview",
        "recruiter_reply",
        "offer",
    }
)


class NotificationService:
    def build(
        self, *, candidate_id: str, event_type: str, occurred_at: datetime, message: str
    ) -> NotificationEvent:
        return NotificationEvent(
            candidate_id=candidate_id,
            event_type=event_type,
            occurred_at=occurred_at,
            message=message,
            immediate=event_type in _IMMEDIATE_EVENTS,
        )


class DigestService:
    def summarize(self, events: Iterable[NotificationEvent]) -> dict[str, int]:
        return dict(sorted(Counter(event.event_type for event in events).items()))


class AnalyticsService:
    def overview(self, metrics: Iterable[ApplicationMetric]) -> dict[str, object]:
        items = tuple(metrics)
        states = Counter(item.state for item in items)
        roles = Counter(item.role_category for item in items)
        adapters = Counter(item.ats_platform for item in items)
        return {
            "applications": len(items),
            "confirmed": states["confirmed"],
            "average_score": (
                round(sum(item.score for item in items) / len(items), 2) if items else None
            ),
            "human_interventions": sum(item.human_interventions for item in items),
            "by_state": dict(sorted(states.items())),
            "by_role_category": dict(sorted(roles.items())),
            "by_ats": dict(sorted(adapters.items())),
        }
