from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.domain.enums import ApplicationState


class InvalidTransitionError(ValueError):
    pass


class IdempotencyConflictError(ValueError):
    pass


TERMINAL_STATES = frozenset(
    {
        ApplicationState.SKIPPED,
        ApplicationState.FAILED_FINAL,
        ApplicationState.CLOSED,
        ApplicationState.REJECTED,
        ApplicationState.OFFER,
        ApplicationState.WITHDRAWN,
    }
)

VALID_TRANSITIONS: dict[ApplicationState, frozenset[ApplicationState]] = {
    ApplicationState.DISCOVERED: frozenset(
        {
            ApplicationState.NORMALIZED,
            ApplicationState.FAILED_RETRYABLE,
            ApplicationState.FAILED_FINAL,
        }
    ),
    ApplicationState.NORMALIZED: frozenset(
        {
            ApplicationState.SECURITY_CHECK,
            ApplicationState.FAILED_RETRYABLE,
            ApplicationState.FAILED_FINAL,
        }
    ),
    ApplicationState.SECURITY_CHECK: frozenset(
        {
            ApplicationState.CLASSIFIED,
            ApplicationState.HUMAN_ACTION_REQUIRED,
            ApplicationState.SKIPPED,
            ApplicationState.FAILED_RETRYABLE,
            ApplicationState.FAILED_FINAL,
        }
    ),
    ApplicationState.CLASSIFIED: frozenset(
        {ApplicationState.SCORED, ApplicationState.FAILED_RETRYABLE, ApplicationState.FAILED_FINAL}
    ),
    ApplicationState.SCORED: frozenset(
        {ApplicationState.SKIPPED, ApplicationState.SHORTLISTED, ApplicationState.FAILED_FINAL}
    ),
    ApplicationState.SKIPPED: frozenset(),
    ApplicationState.SHORTLISTED: frozenset(
        {ApplicationState.CANDIDATE_SNAPSHOT_CREATED, ApplicationState.FAILED_FINAL}
    ),
    ApplicationState.CANDIDATE_SNAPSHOT_CREATED: frozenset(
        {ApplicationState.MATERIALS_GENERATING, ApplicationState.FAILED_FINAL}
    ),
    ApplicationState.MATERIALS_GENERATING: frozenset(
        {
            ApplicationState.MATERIALS_READY,
            ApplicationState.FAILED_RETRYABLE,
            ApplicationState.FAILED_FINAL,
        }
    ),
    ApplicationState.MATERIALS_READY: frozenset(
        {ApplicationState.REVIEW_PENDING, ApplicationState.FAILED_FINAL}
    ),
    ApplicationState.REVIEW_PENDING: frozenset(
        {
            ApplicationState.REVIEW_FAILED,
            ApplicationState.APPLICATION_STARTED,
            ApplicationState.HUMAN_ACTION_REQUIRED,
            ApplicationState.FAILED_RETRYABLE,
            ApplicationState.FAILED_FINAL,
        }
    ),
    ApplicationState.REVIEW_FAILED: frozenset(
        {ApplicationState.MATERIALS_GENERATING, ApplicationState.FAILED_FINAL}
    ),
    ApplicationState.APPLICATION_STARTED: frozenset(
        {
            ApplicationState.FORM_FILLING,
            ApplicationState.FAILED_RETRYABLE,
            ApplicationState.FAILED_FINAL,
        }
    ),
    ApplicationState.FORM_FILLING: frozenset(
        {
            ApplicationState.HUMAN_ACTION_REQUIRED,
            ApplicationState.FINAL_VALIDATION,
            ApplicationState.FAILED_RETRYABLE,
            ApplicationState.FAILED_FINAL,
        }
    ),
    ApplicationState.HUMAN_ACTION_REQUIRED: frozenset(
        {
            ApplicationState.FORM_FILLING,
            ApplicationState.FINAL_VALIDATION,
            ApplicationState.CLOSED,
            ApplicationState.WITHDRAWN,
        }
    ),
    ApplicationState.FINAL_VALIDATION: frozenset(
        {
            ApplicationState.READY_TO_SUBMIT,
            ApplicationState.REVIEW_FAILED,
            ApplicationState.HUMAN_ACTION_REQUIRED,
            ApplicationState.FAILED_FINAL,
        }
    ),
    ApplicationState.READY_TO_SUBMIT: frozenset(
        {
            ApplicationState.SUBMITTING,
            ApplicationState.HUMAN_ACTION_REQUIRED,
            ApplicationState.WITHDRAWN,
            ApplicationState.FAILED_FINAL,
        }
    ),
    ApplicationState.SUBMITTING: frozenset(
        {
            ApplicationState.SUBMITTED,
            ApplicationState.UNKNOWN_AFTER_CLICK,
            ApplicationState.FAILED_RETRYABLE,
            ApplicationState.FAILED_FINAL,
        }
    ),
    ApplicationState.SUBMITTED: frozenset(
        {
            ApplicationState.CONFIRMED,
            ApplicationState.FAILED_RETRYABLE,
            ApplicationState.FAILED_FINAL,
        }
    ),
    ApplicationState.CONFIRMED: frozenset(
        {
            ApplicationState.CLOSED,
            ApplicationState.REJECTED,
            ApplicationState.INTERVIEW,
            ApplicationState.OFFER,
        }
    ),
    ApplicationState.UNKNOWN_AFTER_CLICK: frozenset(
        {ApplicationState.CONFIRMED, ApplicationState.FAILED_FINAL}
    ),
    ApplicationState.FAILED_RETRYABLE: frozenset(
        {
            ApplicationState.SECURITY_CHECK,
            ApplicationState.MATERIALS_GENERATING,
            ApplicationState.REVIEW_PENDING,
            ApplicationState.FORM_FILLING,
            ApplicationState.FINAL_VALIDATION,
            ApplicationState.SUBMITTING,
            ApplicationState.FAILED_FINAL,
        }
    ),
    ApplicationState.FAILED_FINAL: frozenset(),
    ApplicationState.CLOSED: frozenset(),
    ApplicationState.REJECTED: frozenset(),
    ApplicationState.INTERVIEW: frozenset(
        {ApplicationState.OFFER, ApplicationState.REJECTED, ApplicationState.CLOSED}
    ),
    ApplicationState.OFFER: frozenset(),
    ApplicationState.WITHDRAWN: frozenset(),
}


@dataclass(frozen=True, slots=True)
class TransitionCommand:
    candidate_id: str
    application_id: UUID
    current_state: ApplicationState
    target_state: ApplicationState
    idempotency_key: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class TransitionResult:
    previous_state: ApplicationState
    state: ApplicationState
    replayed: bool


class ApplicationStateMachine:
    """Validate typed transitions with an in-process idempotency ledger.

    Durable callers also persist the key in ApplicationEvent, whose database
    uniqueness constraint provides cross-process replay protection.
    """

    def __init__(self) -> None:
        self._processed: dict[tuple[str, UUID, str], TransitionCommand] = {}

    def apply(self, command: TransitionCommand) -> TransitionResult:
        if not command.idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")
        ledger_key = (command.candidate_id, command.application_id, command.idempotency_key)
        existing = self._processed.get(ledger_key)
        if existing is not None:
            if existing != command:
                raise IdempotencyConflictError(
                    "idempotency key was already used for another command"
                )
            return TransitionResult(command.current_state, command.target_state, replayed=True)
        if command.target_state not in VALID_TRANSITIONS[command.current_state]:
            raise InvalidTransitionError(
                f"invalid transition: {command.current_state.value} -> {command.target_state.value}"
            )
        self._processed[ledger_key] = command
        return TransitionResult(command.current_state, command.target_state, replayed=False)
