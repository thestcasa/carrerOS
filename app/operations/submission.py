from __future__ import annotations

from app.operations.contracts import BackendSubmissionEvidence, SubmissionOutcome


def confirmed_outcome(evidence: BackendSubmissionEvidence) -> SubmissionOutcome:
    """Project backend evidence without ever inferring success from an attempted action."""
    if not evidence.backend_confirmation_detected:
        return SubmissionOutcome(
            application_id=evidence.application_id,
            candidate_id=evidence.candidate_id,
            status="confirmation_missing",
            successful=False,
            confirmation_reference=None,
            receipt_sha256=None,
        )
    return SubmissionOutcome(
        application_id=evidence.application_id,
        candidate_id=evidence.candidate_id,
        status="confirmed",
        successful=True,
        confirmation_reference=evidence.confirmation_reference,
        receipt_sha256=evidence.receipt_sha256,
    )
