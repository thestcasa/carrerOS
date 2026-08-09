"""Controlled final-submission boundary; disabled unless explicitly enabled by runtime policy."""

from app.submission.acceptance import (
    SyntheticAdapterAcceptanceResult,
    SyntheticGreenhouseAcceptanceRunner,
)
from app.submission.contracts import (
    ControlledAuthorizationRequest,
    ControlledGreenhouseFormPayload,
    ControlledSubmissionCommand,
    ControlledSubmissionError,
    ControlledSubmissionExecutionView,
    ControlledSubmissionExecutor,
    ControlledSubmissionPreparationRequest,
    ControlledSubmissionRequest,
    ControlledSubmissionResult,
    ControlledSubmissionUncertainError,
    GreenhouseFormInspection,
    PreparedControlledSubmission,
)
from app.submission.greenhouse import GreenhouseControlledAdapter
from app.submission.playwright_executor import GreenhousePlaywrightExecutor

__all__ = [
    "ControlledAuthorizationRequest",
    "ControlledGreenhouseFormPayload",
    "ControlledSubmissionCommand",
    "ControlledSubmissionError",
    "ControlledSubmissionExecutionView",
    "ControlledSubmissionExecutor",
    "ControlledSubmissionPreparationRequest",
    "ControlledSubmissionRequest",
    "ControlledSubmissionResult",
    "ControlledSubmissionUncertainError",
    "GreenhouseControlledAdapter",
    "GreenhouseFormInspection",
    "GreenhousePlaywrightExecutor",
    "PreparedControlledSubmission",
    "SyntheticAdapterAcceptanceResult",
    "SyntheticGreenhouseAcceptanceRunner",
]
