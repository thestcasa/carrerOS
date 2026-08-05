"""Synthetic-only operational policy and reporting services."""

from app.operations.authorization import AuthorizationConsumer, AuthorizationConsumptionError
from app.operations.contracts import (
    ApplicationMetric,
    AutomationMode,
    AutomationReadiness,
    BackendSubmissionEvidence,
    NotificationEvent,
    SubmissionOutcome,
)
from app.operations.policy import AutomationGuard, EmergencyStop, RateLimiter, RateLimitPolicy
from app.operations.reporting import AnalyticsService, DigestService, NotificationService
from app.operations.submission import confirmed_outcome

__all__ = [
    "AnalyticsService",
    "ApplicationMetric",
    "AuthorizationConsumer",
    "AuthorizationConsumptionError",
    "AutomationGuard",
    "AutomationMode",
    "AutomationReadiness",
    "BackendSubmissionEvidence",
    "DigestService",
    "EmergencyStop",
    "NotificationEvent",
    "NotificationService",
    "RateLimitPolicy",
    "RateLimiter",
    "SubmissionOutcome",
    "confirmed_outcome",
]
