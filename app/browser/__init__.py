"""Restricted synthetic ATS dry-run boundary.

This package deliberately exposes no final-submit operation and performs no network access.
"""

from app.browser.contracts import (
    DryRunRequest,
    DryRunResult,
    FieldKind,
    FormField,
    HumanActionReason,
    SyntheticForm,
    UploadArtifact,
)
from app.browser.dry_run import BrowserDryRunError, SyntheticBrowserDryRunner
from app.browser.paths import CandidateSessionPaths

__all__ = [
    "BrowserDryRunError",
    "CandidateSessionPaths",
    "DryRunRequest",
    "DryRunResult",
    "FieldKind",
    "FormField",
    "HumanActionReason",
    "SyntheticBrowserDryRunner",
    "SyntheticForm",
    "UploadArtifact",
]
