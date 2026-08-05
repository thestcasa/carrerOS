"""Restricted synthetic ATS dry-run boundary.

This package deliberately exposes no final-submit operation. Its optional Playwright worker may
navigate only to loopback synthetic fixtures.
"""

from app.browser.contracts import (
    DryRunRequest,
    DryRunResult,
    FieldKind,
    FormField,
    HumanActionReason,
    PlaywrightDryRunRequest,
    PlaywrightDryRunResult,
    SyntheticForm,
    UploadArtifact,
)
from app.browser.dry_run import BrowserDryRunError, SyntheticBrowserDryRunner
from app.browser.paths import CandidateSessionPaths
from app.browser.playwright_worker import RestrictedPlaywrightWorker

__all__ = [
    "BrowserDryRunError",
    "CandidateSessionPaths",
    "DryRunRequest",
    "DryRunResult",
    "FieldKind",
    "FormField",
    "HumanActionReason",
    "PlaywrightDryRunRequest",
    "PlaywrightDryRunResult",
    "RestrictedPlaywrightWorker",
    "SyntheticBrowserDryRunner",
    "SyntheticForm",
    "UploadArtifact",
]
