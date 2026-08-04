from enum import StrEnum


class ApplicationState(StrEnum):
    DISCOVERED = "discovered"
    NORMALIZED = "normalized"
    SECURITY_CHECK = "security_check"
    CLASSIFIED = "classified"
    SCORED = "scored"
    SKIPPED = "skipped"
    SHORTLISTED = "shortlisted"
    CANDIDATE_SNAPSHOT_CREATED = "candidate_snapshot_created"
    MATERIALS_GENERATING = "materials_generating"
    MATERIALS_READY = "materials_ready"
    REVIEW_PENDING = "review_pending"
    REVIEW_FAILED = "review_failed"
    APPLICATION_STARTED = "application_started"
    FORM_FILLING = "form_filling"
    HUMAN_ACTION_REQUIRED = "human_action_required"
    FINAL_VALIDATION = "final_validation"
    READY_TO_SUBMIT = "ready_to_submit"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_FINAL = "failed_final"
    CLOSED = "closed"
    REJECTED = "rejected"
    INTERVIEW = "interview"
    OFFER = "offer"
    WITHDRAWN = "withdrawn"


class ApplicationOutcome(StrEnum):
    PENDING = "pending"
    SKIPPED = "skipped"
    SUBMITTED = "submitted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class DocumentKind(StrEnum):
    CV = "cv"
    COVER_LETTER = "cover_letter"
    OTHER = "other"


class ReviewDecision(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    HUMAN_REVIEW = "human_review"


class HumanActionKind(StrEnum):
    APPROVE = "approve"
    DENY = "deny"
    EDIT = "edit"
    PAUSE = "pause"
