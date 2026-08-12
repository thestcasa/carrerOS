from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.candidates.service import CandidateNotFoundError, CandidateService
from app.discovery.providers import ProviderPlatform
from app.domain.models import (
    CandidateDiscoveryRun,
    CandidateDiscoverySource,
    CandidateDiscoverySourceCommand,
    CandidateSettingsRecord,
)
from app.job_service import DiscoveryRequest, JobService
from app.tasks import TaskLeaseLostError, TaskQueue, TaskView


class ScheduledDiscoveryError(ValueError):
    pass


class PayloadFetcher(Protocol):
    def fetch(
        self, provider: ProviderPlatform, board_token: str
    ) -> tuple[dict[str, object], ...]: ...


class DiscoverySourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["greenhouse", "lever", "ashby"]
    company: str = Field(min_length=1, max_length=255)
    company_domain: str = Field(
        pattern=r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$",
        min_length=3,
        max_length=255,
    )
    board_token: str = Field(pattern=r"^[A-Za-z0-9_-]+$", min_length=1, max_length=100)
    cadence_minutes: int = Field(default=60, ge=15, le=1440)
    enabled: bool = True

    @field_validator("company")
    @classmethod
    def company_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("company must not be blank")
        return value


class DiscoverySourceView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: UUID
    candidate_id: str
    provider: str
    company: str
    company_domain: str
    board_token: str
    enabled: bool
    cadence_minutes: int
    next_run_at: datetime
    last_success_at: datetime | None
    last_error: str | None
    last_status: str | None
    last_discovered: int
    last_unchanged: int


class DiscoverySourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool | None = None
    cadence_minutes: int | None = Field(default=None, ge=15, le=1440)


class ScheduledDiscoveryService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        candidates: CandidateService,
        jobs: JobService,
        fetcher: PayloadFetcher,
    ) -> None:
        self._sessions = session_factory
        self._candidates = candidates
        self._jobs = jobs
        self._fetcher = fetcher

    def create_source(
        self,
        candidate_id: str,
        command: DiscoverySourceCreate,
        idempotency_key: str,
        *,
        now: datetime | None = None,
    ) -> DiscoverySourceView:
        self._candidates.get_config(candidate_id)
        if len(idempotency_key) < 8:
            raise ScheduledDiscoveryError("idempotency key is invalid")
        request_sha256 = hashlib.sha256(
            json.dumps(
                command.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        current = now or datetime.now(UTC)
        try:
            return self._create_source_once(
                candidate_id, command, idempotency_key, request_sha256, current
            )
        except IntegrityError as exc:
            with self._sessions() as session:
                replay = session.scalar(
                    select(CandidateDiscoverySource).where(
                        CandidateDiscoverySource.candidate_id == candidate_id,
                        CandidateDiscoverySource.idempotency_key == idempotency_key,
                    )
                )
                if replay is not None:
                    if replay.request_sha256 != request_sha256:
                        raise ScheduledDiscoveryError(
                            "idempotency key was reused for different source settings"
                        ) from exc
                    return self._view(session, replay)
            raise ScheduledDiscoveryError("discovery source already exists") from exc

    def _create_source_once(
        self,
        candidate_id: str,
        command: DiscoverySourceCreate,
        idempotency_key: str,
        request_sha256: str,
        current: datetime,
    ) -> DiscoverySourceView:
        with self._sessions.begin() as session:
            replay = session.scalar(
                select(CandidateDiscoverySource).where(
                    CandidateDiscoverySource.candidate_id == candidate_id,
                    CandidateDiscoverySource.idempotency_key == idempotency_key,
                )
            )
            if replay is not None:
                if replay.request_sha256 != request_sha256:
                    raise ScheduledDiscoveryError(
                        "idempotency key was reused for different source settings"
                    )
                return self._view(session, replay)
            existing = session.scalar(
                select(CandidateDiscoverySource).where(
                    CandidateDiscoverySource.candidate_id == candidate_id,
                    CandidateDiscoverySource.provider == command.provider,
                    CandidateDiscoverySource.board_token == command.board_token,
                )
            )
            if existing is not None:
                raise ScheduledDiscoveryError("discovery source already exists")
            source = CandidateDiscoverySource(
                candidate_id=candidate_id,
                provider=command.provider,
                company=command.company,
                company_domain=command.company_domain,
                board_token=command.board_token,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                cadence_minutes=command.cadence_minutes,
                enabled=command.enabled,
                next_run_at=current,
            )
            session.add(source)
            session.flush()
            return self._view(session, source)

    def update_source(
        self,
        candidate_id: str,
        source_id: UUID,
        command: DiscoverySourceUpdate,
        idempotency_key: str,
    ) -> DiscoverySourceView:
        self._candidates.get_config(candidate_id)
        if len(idempotency_key) < 8:
            raise ScheduledDiscoveryError("idempotency key is invalid")
        if command.enabled is None and command.cadence_minutes is None:
            raise ScheduledDiscoveryError("source update is empty")
        request_sha256 = hashlib.sha256(
            json.dumps(
                {
                    "source_id": str(source_id),
                    "command": command.model_dump(mode="json"),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        try:
            return self._update_source_once(
                candidate_id, source_id, command, idempotency_key, request_sha256
            )
        except IntegrityError as exc:
            with self._sessions() as session:
                replay = session.scalar(
                    select(CandidateDiscoverySourceCommand).where(
                        CandidateDiscoverySourceCommand.candidate_id == candidate_id,
                        CandidateDiscoverySourceCommand.idempotency_key == idempotency_key,
                    )
                )
                if replay is not None:
                    if replay.source_id != source_id or replay.request_sha256 != request_sha256:
                        raise ScheduledDiscoveryError(
                            "idempotency key was reused for a different source update"
                        ) from exc
                    return DiscoverySourceView.model_validate(replay.result)
            raise ScheduledDiscoveryError("discovery source update conflicted") from exc

    def _update_source_once(
        self,
        candidate_id: str,
        source_id: UUID,
        command: DiscoverySourceUpdate,
        idempotency_key: str,
        request_sha256: str,
    ) -> DiscoverySourceView:
        with self._sessions.begin() as session:
            replay = session.scalar(
                select(CandidateDiscoverySourceCommand).where(
                    CandidateDiscoverySourceCommand.candidate_id == candidate_id,
                    CandidateDiscoverySourceCommand.idempotency_key == idempotency_key,
                )
            )
            if replay is not None:
                if replay.source_id != source_id or replay.request_sha256 != request_sha256:
                    raise ScheduledDiscoveryError(
                        "idempotency key was reused for a different source update"
                    )
                return DiscoverySourceView.model_validate(replay.result)
            source = session.scalar(
                select(CandidateDiscoverySource).where(
                    CandidateDiscoverySource.id == source_id,
                    CandidateDiscoverySource.candidate_id == candidate_id,
                )
            )
            if source is None:
                raise ScheduledDiscoveryError("discovery source was not found")
            if command.enabled is not None:
                source.enabled = command.enabled
            if command.cadence_minutes is not None:
                source.cadence_minutes = command.cadence_minutes
            session.flush()
            result = self._view(session, source)
            session.add(
                CandidateDiscoverySourceCommand(
                    candidate_id=candidate_id,
                    source_id=source_id,
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    result=result.model_dump(mode="json"),
                )
            )
            return result

    def list_sources(self, candidate_id: str) -> tuple[DiscoverySourceView, ...]:
        self._candidates.get_config(candidate_id)
        with self._sessions() as session:
            sources = session.scalars(
                select(CandidateDiscoverySource)
                .where(CandidateDiscoverySource.candidate_id == candidate_id)
                .order_by(CandidateDiscoverySource.company, CandidateDiscoverySource.provider)
            ).all()
            return tuple(self._view(session, source) for source in sources)

    def enqueue_due(self, queue: TaskQueue, *, now: datetime | None = None) -> tuple[TaskView, ...]:
        current = now or datetime.now(UTC)
        scheduled: list[TaskView] = []
        due: list[tuple[UUID, str]] = []
        with self._sessions() as session:
            sources = session.scalars(
                select(CandidateDiscoverySource).where(
                    CandidateDiscoverySource.enabled.is_(True),
                    CandidateDiscoverySource.next_run_at <= current,
                )
            ).all()
            for source in sources:
                due.append((source.id, source.candidate_id))
        for source_id, candidate_id in due:
            try:
                with self._candidates.lifecycle_read(candidate_id):
                    with self._sessions() as session:
                        due_source = session.scalar(
                            select(CandidateDiscoverySource).where(
                                CandidateDiscoverySource.id == source_id,
                                CandidateDiscoverySource.candidate_id == candidate_id,
                                CandidateDiscoverySource.enabled.is_(True),
                                CandidateDiscoverySource.next_run_at <= current,
                            )
                        )
                        settings = session.scalar(
                            select(CandidateSettingsRecord).where(
                                CandidateSettingsRecord.candidate_id == candidate_id
                            )
                        )
                        if due_source is None or not self._source_is_allowed(due_source, settings):
                            continue
                        cadence_minutes = due_source.cadence_minutes
                    cadence_bucket = str(int(current.timestamp() // (cadence_minutes * 60)))
                    scheduled.append(
                        queue.enqueue(
                            candidate_id=candidate_id,
                            kind="discover_source",
                            idempotency_key=f"discover:{source_id}:{cadence_bucket}",
                            payload={
                                "source_id": str(source_id),
                                "cadence_bucket": cadence_bucket,
                            },
                            scheduled_for=current,
                        )
                    )
                    with self._sessions.begin() as session:
                        stored_source = session.get(CandidateDiscoverySource, source_id)
                        if stored_source is not None:
                            stored_source.next_run_at = current + timedelta(minutes=cadence_minutes)
            except (CandidateNotFoundError, TaskLeaseLostError):
                continue
            except IntegrityError as exc:
                if "candidate is deleted" in str(exc).casefold():
                    continue
                raise
        return tuple(scheduled)

    def execute_task(self, task: TaskView, *, now: datetime | None = None) -> None:
        if task.kind != "discover_source":
            raise ScheduledDiscoveryError("task is not a discovery source task")
        try:
            source_id = UUID(str(task.payload["source_id"]))
            cadence_bucket = str(task.payload["cadence_bucket"])
        except (KeyError, ValueError) as exc:
            raise ScheduledDiscoveryError("discovery task payload is invalid") from exc
        current = now or datetime.now(UTC)
        with self._sessions.begin() as session:
            source = session.scalar(
                select(CandidateDiscoverySource).where(
                    CandidateDiscoverySource.id == source_id,
                    CandidateDiscoverySource.candidate_id == task.candidate_id,
                )
            )
            if source is None:
                raise ScheduledDiscoveryError("discovery source is missing")
            settings = session.scalar(
                select(CandidateSettingsRecord).where(
                    CandidateSettingsRecord.candidate_id == task.candidate_id
                )
            )
            self._candidates.get_config(task.candidate_id)
            if not self._source_is_allowed(source, settings):
                return
            run = session.scalar(
                select(CandidateDiscoveryRun).where(
                    CandidateDiscoveryRun.source_id == source_id,
                    CandidateDiscoveryRun.cadence_bucket == cadence_bucket,
                )
            )
            if run is not None and run.status == "completed":
                return
            if run is None:
                run = CandidateDiscoveryRun(
                    candidate_id=task.candidate_id,
                    source_id=source_id,
                    cadence_bucket=cadence_bucket,
                    status="running",
                    started_at=current,
                    lease_attempt=task.attempts,
                )
                session.add(run)
            else:
                acquired = cast(
                    CursorResult[Any],
                    session.execute(
                        update(CandidateDiscoveryRun)
                        .where(
                            CandidateDiscoveryRun.id == run.id,
                            CandidateDiscoveryRun.status != "completed",
                            CandidateDiscoveryRun.lease_attempt < task.attempts,
                        )
                        .values(
                            status="running",
                            started_at=current,
                            completed_at=None,
                            error_code=None,
                            lease_attempt=task.attempts,
                        )
                    ),
                )
                if acquired.rowcount != 1:
                    raise ScheduledDiscoveryError("discovery task lease was superseded")
            provider = cast(ProviderPlatform, source.provider)
            board_token = source.board_token
            company = source.company
            company_domain = source.company_domain

        def guard_transaction(session: Session) -> None:
            owned_run = session.scalar(
                select(CandidateDiscoveryRun)
                .where(
                    CandidateDiscoveryRun.source_id == source_id,
                    CandidateDiscoveryRun.cadence_bucket == cadence_bucket,
                )
                .with_for_update()
            )
            guarded_source = session.scalar(
                select(CandidateDiscoverySource).where(
                    CandidateDiscoverySource.id == source_id,
                    CandidateDiscoverySource.candidate_id == task.candidate_id,
                )
            )
            guarded_settings = session.scalar(
                select(CandidateSettingsRecord).where(
                    CandidateSettingsRecord.candidate_id == task.candidate_id
                )
            )
            if (
                owned_run is None
                or owned_run.status != "running"
                or owned_run.lease_attempt != task.attempts
                or guarded_source is None
                or not self._source_is_allowed(guarded_source, guarded_settings)
            ):
                raise ScheduledDiscoveryError("discovery task lease was superseded")

        try:
            payloads = self._fetcher.fetch(provider, board_token)
            request = DiscoveryRequest(
                candidate_id=task.candidate_id,
                platform=provider,
                company=company,
                company_domain=company_domain,
                payloads=payloads,
            )
            payload_sha256 = hashlib.sha256(
                json.dumps(
                    request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
            result = self._jobs.discover(
                request,
                idempotency_key=f"scheduled:{source_id}:{cadence_bucket}:{payload_sha256}",
                transaction_guard=guard_transaction,
            )
            for job_id in result.changed_job_ids:
                self._jobs.analyze(
                    task.candidate_id,
                    job_id,
                    f"scheduled-analyze:{source_id}:{cadence_bucket}:{payload_sha256}:{job_id}",
                    transaction_guard=guard_transaction,
                )
        except Exception as exc:
            error_code = getattr(exc, "code", type(exc).__name__)[:64]
            with self._sessions.begin() as session:
                finished = cast(
                    CursorResult[Any],
                    session.execute(
                        update(CandidateDiscoveryRun)
                        .where(
                            CandidateDiscoveryRun.source_id == source_id,
                            CandidateDiscoveryRun.cadence_bucket == cadence_bucket,
                            CandidateDiscoveryRun.lease_attempt == task.attempts,
                            CandidateDiscoveryRun.status == "running",
                        )
                        .values(status="failed", error_code=error_code, completed_at=current)
                    ),
                )
                source = session.get(CandidateDiscoverySource, source_id)
                if finished.rowcount != 1 or source is None:
                    raise ScheduledDiscoveryError("discovery task lease was superseded") from exc
                source.last_error = error_code
            raise ScheduledDiscoveryError(error_code) from exc
        with self._sessions.begin() as session:
            finished = cast(
                CursorResult[Any],
                session.execute(
                    update(CandidateDiscoveryRun)
                    .where(
                        CandidateDiscoveryRun.source_id == source_id,
                        CandidateDiscoveryRun.cadence_bucket == cadence_bucket,
                        CandidateDiscoveryRun.lease_attempt == task.attempts,
                        CandidateDiscoveryRun.status == "running",
                    )
                    .values(
                        status="completed",
                        discovered_count=result.discovered,
                        unchanged_count=result.unchanged,
                        error_code=None,
                        completed_at=current,
                    )
                ),
            )
            source = session.get(CandidateDiscoverySource, source_id)
            if finished.rowcount != 1 or source is None:
                raise ScheduledDiscoveryError("discovery task lease was superseded")
            source.last_success_at = current
            source.last_error = None

    @staticmethod
    def _source_is_allowed(
        source: CandidateDiscoverySource, settings: CandidateSettingsRecord | None
    ) -> bool:
        return bool(
            source.enabled
            and settings is not None
            and settings.discovery_enabled
            and source.provider in settings.allowed_ats_adapters
        )

    @staticmethod
    def _view(session: Session, source: CandidateDiscoverySource) -> DiscoverySourceView:
        run = session.scalar(
            select(CandidateDiscoveryRun)
            .where(CandidateDiscoveryRun.source_id == source.id)
            .order_by(CandidateDiscoveryRun.started_at.desc())
            .limit(1)
        )
        return DiscoverySourceView(
            source_id=source.id,
            candidate_id=source.candidate_id,
            provider=source.provider,
            company=source.company,
            company_domain=source.company_domain,
            board_token=source.board_token,
            enabled=source.enabled,
            cadence_minutes=source.cadence_minutes,
            next_run_at=source.next_run_at,
            last_success_at=source.last_success_at,
            last_error=source.last_error,
            last_status=run.status if run else None,
            last_discovered=run.discovered_count if run else 0,
            last_unchanged=run.unchanged_count if run else 0,
        )
