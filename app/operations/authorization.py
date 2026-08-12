from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.enums import ApplicationState
from app.domain.models import Application, SubmissionAuthorizationRecord
from app.submission_gate import SubmissionAuthorization


class AuthorizationConsumptionError(PermissionError):
    pass


class AuthorizationConsumer:
    """Persist and atomically consume a bound, unexpired gate authorization once."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    def consume(
        self,
        authorization: SubmissionAuthorization,
        *,
        candidate_id: str,
        application_id: UUID,
        workflow_state: ApplicationState = ApplicationState.READY_TO_SUBMIT,
        now: datetime | None = None,
    ) -> UUID:
        if not isinstance(authorization, SubmissionAuthorization):
            raise AuthorizationConsumptionError("authorization was not issued by SubmissionGate")
        checked_at = now or datetime.now(UTC)
        if checked_at.tzinfo is None:
            raise AuthorizationConsumptionError("authorization check time must be timezone-aware")
        if authorization.candidate_id != candidate_id:
            raise AuthorizationConsumptionError("authorization candidate binding mismatch")
        if authorization.application_id != application_id:
            raise AuthorizationConsumptionError("authorization application binding mismatch")
        if authorization.workflow_state is not workflow_state:
            raise AuthorizationConsumptionError("authorization workflow state binding mismatch")
        if checked_at < authorization.issued_at or checked_at >= authorization.expires_at:
            raise AuthorizationConsumptionError("authorization is not currently valid")
        try:
            with self._sessions.begin() as session:
                application = session.scalar(
                    select(Application).where(
                        Application.id == application_id,
                        Application.candidate_id == candidate_id,
                    )
                )
                if application is None:
                    raise AuthorizationConsumptionError(
                        "authorization application binding was not found"
                    )
                if application.state is not workflow_state:
                    raise AuthorizationConsumptionError(
                        "authorization no longer matches the persisted workflow state"
                    )
                record = session.get(SubmissionAuthorizationRecord, authorization.authorization_id)
                if record is not None:
                    if record.consumed_at is not None:
                        raise AuthorizationConsumptionError("authorization was already consumed")
                    if (
                        record.candidate_id != candidate_id
                        or record.application_id != application_id
                        or record.workflow_state is not workflow_state
                        or record.issued_at != authorization.issued_at
                        or record.expires_at != authorization.expires_at
                    ):
                        raise AuthorizationConsumptionError(
                            "authorization record does not match the gate decision"
                        )
                else:
                    record = SubmissionAuthorizationRecord(
                        authorization_id=authorization.authorization_id,
                        candidate_id=candidate_id,
                        application_id=application_id,
                        workflow_state=workflow_state,
                        issued_at=authorization.issued_at,
                        expires_at=authorization.expires_at,
                    )
                    session.add(record)
                record.consumed_at = checked_at
        except IntegrityError as exc:
            raise AuthorizationConsumptionError("authorization was already consumed") from exc
        return authorization.authorization_id
