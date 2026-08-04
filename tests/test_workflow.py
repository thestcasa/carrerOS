from __future__ import annotations

from uuid import uuid4

import pytest

from app.domain.enums import ApplicationState
from app.workflow import (
    ApplicationStateMachine,
    IdempotencyConflictError,
    InvalidTransitionError,
    TransitionCommand,
)


def test_invalid_state_transition_is_rejected() -> None:
    machine = ApplicationStateMachine()
    command = TransitionCommand(
        candidate_id="candidate_alpha",
        application_id=uuid4(),
        current_state=ApplicationState.DISCOVERED,
        target_state=ApplicationState.SUBMITTED,
        idempotency_key="transition-1",
    )

    with pytest.raises(InvalidTransitionError):
        machine.apply(command)


def test_terminal_failure_cannot_be_retried() -> None:
    machine = ApplicationStateMachine()
    command = TransitionCommand(
        candidate_id="candidate_alpha",
        application_id=uuid4(),
        current_state=ApplicationState.FAILED_FINAL,
        target_state=ApplicationState.NORMALIZED,
        idempotency_key="transition-2",
    )

    with pytest.raises(InvalidTransitionError):
        machine.apply(command)


def test_transition_replay_is_idempotent_and_conflicts_are_rejected() -> None:
    machine = ApplicationStateMachine()
    application_id = uuid4()
    command = TransitionCommand(
        candidate_id="candidate_alpha",
        application_id=application_id,
        current_state=ApplicationState.DISCOVERED,
        target_state=ApplicationState.NORMALIZED,
        idempotency_key="transition-3",
    )

    assert machine.apply(command).replayed is False
    assert machine.apply(command).replayed is True

    conflict = TransitionCommand(
        candidate_id="candidate_alpha",
        application_id=application_id,
        current_state=ApplicationState.DISCOVERED,
        target_state=ApplicationState.WITHDRAWN,
        idempotency_key="transition-3",
    )
    with pytest.raises(IdempotencyConflictError):
        machine.apply(conflict)


def test_retryable_failure_can_return_to_its_processing_state() -> None:
    result = ApplicationStateMachine().apply(
        TransitionCommand(
            candidate_id="candidate_alpha",
            application_id=uuid4(),
            current_state=ApplicationState.FAILED_RETRYABLE,
            target_state=ApplicationState.REVIEW_PENDING,
            idempotency_key="retry-review",
        )
    )
    assert result.state is ApplicationState.REVIEW_PENDING
