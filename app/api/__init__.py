from __future__ import annotations

import json
import secrets
from collections.abc import Iterator
from datetime import timedelta
from typing import Annotated, Any, Literal, cast
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.applications import (
    AnalyticsOverview,
    AnswerRevisionRequest,
    ApplicationConflictError,
    ApplicationDetail,
    ApplicationNotFoundError,
    ApplicationService,
    ApplicationSummary,
    ArtifactView,
    AuthorizationView,
    ControlledAuthorizationRequest,
    ControlledSubmissionCommand,
    ControlledSubmissionExecutionView,
    CorrespondenceIngestRequest,
    CorrespondenceView,
    DryRunCommand,
    HumanActionView,
    MaterialRevisionRequest,
    NotificationView,
    SecurityEventView,
    SettingsUpdate,
    SettingsView,
    SyntheticSubmissionRequest,
)
from app.applications.contracts import EventView, SubmissionResultView
from app.auth.lifecycle import (
    CandidateDeletionError,
    CandidateDeletionRequest,
    CandidateDeletionView,
    CandidateExportView,
    CandidateLifecycleService,
)
from app.auth.tokens import LocalTokenService, TokenValidationError
from app.candidates.cv_import import CVImportDraft, CVImportRequest
from app.candidates.loader import CandidateConfigError
from app.candidates.portability import CandidatePortabilityError
from app.candidates.readiness import ReadinessReport
from app.candidates.service import (
    CandidateConfigurationImportRequest,
    CandidateConfigurationImportResult,
    CandidateCreateRequest,
    CandidateDetail,
    CandidateIdempotencyError,
    CandidateImportRequest,
    CandidateNotFoundError,
    CandidateSectionUpdate,
    CandidateService,
    CandidateSummary,
    CandidateUpdateError,
    CandidateUpdateResult,
    CandidateValidationReport,
)
from app.candidates.snapshot import CandidateSnapshot
from app.core.settings import Settings
from app.correspondence import InterviewPreparationPackage
from app.db import build_engine, build_session_factory
from app.discovery.providers import ProviderFeedClient
from app.discovery.scheduled import (
    DiscoverySourceCreate,
    DiscoverySourceUpdate,
    DiscoverySourceView,
    ScheduledDiscoveryError,
    ScheduledDiscoveryService,
)
from app.discovery.verification import ProviderJobSourceVerifier
from app.health import HealthChecker, HealthProbe, HealthReport
from app.job_service import (
    DiscoveryRequest,
    DiscoveryResult,
    JobCommandConflictError,
    JobNotFoundError,
    JobService,
    JobView,
)

_CV_IMPORT_MAX_REQUEST_BYTES = 3_010_000
# A 1 MiB UTF-8 document can expand to six bytes per character when embedded in JSON.
_CONFIGURATION_IMPORT_MAX_REQUEST_BYTES = 6_300_000
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=8, max_length=128),
]


class _CandidateImportBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, cv_max_bytes: int, configuration_max_bytes: int) -> None:
        self._app = app
        self._cv_max_bytes = cv_max_bytes
        self._configuration_max_bytes = configuration_max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = self._limit(scope)
        if limit is None:
            await self._app(scope, receive, send)
            return
        max_bytes, error_code, message = limit
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > max_bytes:
                    await self._reject(scope, receive, send, error_code, message)
                    return
            except ValueError:
                await self._reject(scope, receive, send, error_code, message)
                return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_bytes:
                    raise _CandidateImportRequestTooLarge
            return message

        try:
            await self._app(scope, limited_receive, send)
        except _CandidateImportRequestTooLarge:
            await self._reject(scope, receive, send, error_code, message)

    def _limit(self, scope: Scope) -> tuple[int, str, str] | None:
        if scope["type"] != "http" or scope.get("method") != "POST":
            return None
        parts = str(scope.get("path", "")).strip("/").split("/")
        if len(parts) != 4 or parts[:2] != ["api", "candidates"]:
            return None
        if parts[3] == "cv-imports":
            return (
                self._cv_max_bytes,
                "cv_import_too_large",
                "CV import request exceeds the transport limit.",
            )
        if parts[3] == "configuration-import":
            return (
                self._configuration_max_bytes,
                "candidate_import_too_large",
                "Candidate configuration import exceeds the transport limit.",
            )
        return None

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        error_code: str,
        message: str,
    ) -> None:
        response = JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": error_code,
                    "message": message,
                }
            },
        )
        await response(scope, receive, send)


class _CandidateImportRequestTooLarge(Exception):
    pass


def _candidate_service(request: Request) -> CandidateService:
    return cast(CandidateService, request.app.state.candidate_service)


def _health_checker(request: Request) -> HealthChecker:
    return cast(HealthChecker, request.app.state.health_checker)


def _job_service(request: Request) -> JobService:
    return cast(JobService, request.app.state.job_service)


def _application_service(request: Request) -> ApplicationService:
    return cast(ApplicationService, request.app.state.application_service)


def _scheduled_discovery_service(request: Request) -> ScheduledDiscoveryService:
    return cast(ScheduledDiscoveryService, request.app.state.scheduled_discovery_service)


def _candidate_lifecycle_service(request: Request) -> CandidateLifecycleService:
    return cast(CandidateLifecycleService, request.app.state.candidate_lifecycle_service)


CandidateServiceDependency = Annotated[CandidateService, Depends(_candidate_service)]
HealthCheckerDependency = Annotated[HealthChecker, Depends(_health_checker)]
JobServiceDependency = Annotated[JobService, Depends(_job_service)]
ApplicationServiceDependency = Annotated[ApplicationService, Depends(_application_service)]
ScheduledDiscoveryDependency = Annotated[
    ScheduledDiscoveryService, Depends(_scheduled_discovery_service)
]
CandidateLifecycleDependency = Annotated[
    CandidateLifecycleService, Depends(_candidate_lifecycle_service)
]


class _LocalSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str | None = None


class _LocalSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_token: str
    csrf_token: str
    candidate_ids: tuple[str, ...]


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def _candidate_router() -> APIRouter:
    router = APIRouter(prefix="/api/candidates", tags=["candidates"])

    @router.get("", response_model=tuple[CandidateSummary, ...])
    def list_candidates(service: CandidateServiceDependency) -> tuple[CandidateSummary, ...]:
        return service.list_candidates()

    @router.post("", response_model=CandidateDetail)
    def create_candidate(
        candidate: CandidateCreateRequest,
        service: CandidateServiceDependency,
        idempotency_key: IdempotencyKey,
    ) -> CandidateDetail:
        return service.create(candidate, idempotency_key)

    @router.get("/{candidate_id}", response_model=CandidateDetail)
    def get_candidate(candidate_id: str, service: CandidateServiceDependency) -> CandidateDetail:
        return service.get_detail(candidate_id)

    @router.patch("/{candidate_id}", response_model=CandidateUpdateResult)
    def update_candidate(
        candidate_id: str,
        update: CandidateSectionUpdate,
        service: CandidateServiceDependency,
        idempotency_key: IdempotencyKey,
    ) -> CandidateUpdateResult:
        return service.update_section(candidate_id, update, idempotency_key)

    @router.post("/{candidate_id}/validate", response_model=CandidateValidationReport)
    def validate_candidate(
        candidate_id: str, service: CandidateServiceDependency
    ) -> CandidateValidationReport:
        return service.validate(candidate_id)

    @router.get("/{candidate_id}/readiness", response_model=ReadinessReport)
    def candidate_readiness(
        candidate_id: str, service: CandidateServiceDependency
    ) -> ReadinessReport:
        return service.readiness(candidate_id)

    @router.post("/{candidate_id}/snapshot", response_model=CandidateSnapshot)
    def snapshot_candidate(
        candidate_id: str,
        service: CandidateServiceDependency,
        idempotency_key: IdempotencyKey,
    ) -> CandidateSnapshot:
        return service.snapshot_command(candidate_id, idempotency_key)

    @router.post("/{candidate_id}/import", response_model=CandidateUpdateResult)
    def import_candidate_section(
        candidate_id: str,
        imported: CandidateImportRequest,
        service: CandidateServiceDependency,
        idempotency_key: IdempotencyKey,
    ) -> CandidateUpdateResult:
        return service.update_section(
            candidate_id,
            CandidateSectionUpdate(section=imported.section, data=imported.data),
            idempotency_key,
        )

    @router.get("/{candidate_id}/export", response_model=CandidateExportView)
    def export_candidate(
        candidate_id: str, service: CandidateLifecycleDependency, response: Response
    ) -> CandidateExportView:
        exported = service.export_candidate(candidate_id)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Disposition"] = (
            f"attachment; filename*=UTF-8''{quote(candidate_id)}-portable-export.json"
        )
        return exported

    @router.get("/{candidate_id}/configuration-export", response_class=Response)
    def export_candidate_configuration(
        candidate_id: str,
        service: CandidateServiceDependency,
        format: Annotated[Literal["json", "yaml"], Query()] = "json",
    ) -> Response:
        content = service.export_configuration(candidate_id, format)
        extension = "json" if format == "json" else "yaml"
        media_type = "application/json" if format == "json" else "application/yaml"
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": (
                    f"attachment; filename*=UTF-8''{quote(candidate_id)}-configuration.{extension}"
                ),
            },
        )

    @router.post(
        "/{candidate_id}/configuration-import",
        response_model=CandidateConfigurationImportResult,
    )
    def import_candidate_configuration(
        candidate_id: str,
        imported: CandidateConfigurationImportRequest,
        service: CandidateServiceDependency,
        idempotency_key: IdempotencyKey,
    ) -> CandidateConfigurationImportResult:
        return service.import_configuration(candidate_id, imported, idempotency_key)

    @router.delete("/{candidate_id}", response_model=CandidateDeletionView)
    def delete_candidate(
        candidate_id: str,
        command: CandidateDeletionRequest,
        service: CandidateLifecycleDependency,
        idempotency_key: IdempotencyKey,
    ) -> CandidateDeletionView:
        return service.delete_candidate(candidate_id, command, idempotency_key)

    @router.get("/{candidate_id}/deletion", response_model=CandidateDeletionView)
    def deletion_status(
        candidate_id: str, service: CandidateLifecycleDependency
    ) -> CandidateDeletionView:
        return service.deletion_status(candidate_id)

    @router.post("/{candidate_id}/cv-imports", response_model=CVImportDraft)
    def create_cv_import(
        candidate_id: str,
        imported: CVImportRequest,
        service: CandidateServiceDependency,
        idempotency_key: IdempotencyKey,
    ) -> CVImportDraft:
        return service.create_cv_import(candidate_id, imported, idempotency_key)

    @router.post("/{candidate_id}/cv-imports/{import_id}/apply", response_model=CandidateDetail)
    def apply_cv_import(
        candidate_id: str,
        import_id: str,
        service: CandidateServiceDependency,
        idempotency_key: IdempotencyKey,
    ) -> CandidateDetail:
        return service.apply_cv_import(candidate_id, import_id, idempotency_key)

    return router


def _job_router() -> APIRouter:
    router = APIRouter(prefix="/api/jobs", tags=["jobs"])

    @router.post("/discover", response_model=DiscoveryResult)
    def discover_jobs(
        request: DiscoveryRequest,
        service: JobServiceDependency,
        idempotency_key: IdempotencyKey,
    ) -> DiscoveryResult:
        return service.discover(request, idempotency_key)

    @router.get("/sources", response_model=tuple[DiscoverySourceView, ...])
    def list_discovery_sources(
        service: ScheduledDiscoveryDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
    ) -> tuple[DiscoverySourceView, ...]:
        return service.list_sources(candidate_id)

    @router.post("/sources", response_model=DiscoverySourceView)
    def create_discovery_source(
        command: DiscoverySourceCreate,
        service: ScheduledDiscoveryDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
        idempotency_key: IdempotencyKey,
    ) -> DiscoverySourceView:
        return service.create_source(candidate_id, command, idempotency_key)

    @router.patch("/sources/{source_id}", response_model=DiscoverySourceView)
    def update_discovery_source(
        source_id: UUID,
        command: DiscoverySourceUpdate,
        service: ScheduledDiscoveryDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
        idempotency_key: IdempotencyKey,
    ) -> DiscoverySourceView:
        return service.update_source(candidate_id, source_id, command, idempotency_key)

    @router.get("", response_model=tuple[JobView, ...])
    def list_jobs(
        service: JobServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
    ) -> tuple[JobView, ...]:
        return service.list_jobs(candidate_id)

    @router.get("/{job_id}", response_model=JobView)
    def get_job(
        job_id: UUID,
        service: JobServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
    ) -> JobView:
        return service.get_job(candidate_id, job_id)

    @router.post("/{job_id}/analyze", response_model=JobView)
    def analyze_job(
        job_id: UUID,
        service: JobServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
        idempotency_key: IdempotencyKey,
    ) -> JobView:
        return service.analyze(candidate_id, job_id, idempotency_key)

    @router.post("/{job_id}/generate-materials", response_model=ApplicationDetail)
    def generate_materials(
        job_id: UUID,
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
        idempotency_key: IdempotencyKey,
    ) -> ApplicationDetail:
        return service.generate_materials(candidate_id, job_id, idempotency_key)

    for command_name in ("verify", "shortlist", "skip"):

        def run_command(
            job_id: UUID,
            service: JobServiceDependency,
            candidate_id: Annotated[str, Query(min_length=1)],
            idempotency_key: IdempotencyKey,
            _command: str = command_name,
        ) -> JobView:
            return service.command(candidate_id, job_id, cast(Any, _command), idempotency_key)

        router.add_api_route(
            f"/{{job_id}}/{command_name}", run_command, methods=["POST"], response_model=JobView
        )

    return router


def _application_router() -> APIRouter:
    router = APIRouter(prefix="/api/applications", tags=["applications"])

    @router.get("", response_model=tuple[ApplicationSummary, ...])
    def list_applications(
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
    ) -> tuple[ApplicationSummary, ...]:
        return service.list_applications(candidate_id)

    @router.get("/{application_id}", response_model=ApplicationDetail)
    def get_application(
        application_id: UUID,
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
    ) -> ApplicationDetail:
        return service.get_application(candidate_id, application_id)

    @router.post("/{application_id}/approve-materials", response_model=ApplicationDetail)
    def approve_materials(
        application_id: UUID,
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
        idempotency_key: IdempotencyKey,
    ) -> ApplicationDetail:
        return service.approve_materials(candidate_id, application_id, idempotency_key)

    @router.post("/{application_id}/materials/revisions", response_model=ApplicationDetail)
    def revise_material(
        application_id: UUID,
        revision: MaterialRevisionRequest,
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
        idempotency_key: IdempotencyKey,
    ) -> ApplicationDetail:
        return service.revise_material(candidate_id, application_id, revision, idempotency_key)

    @router.post("/{application_id}/answers/revisions", response_model=ApplicationDetail)
    def revise_answer(
        application_id: UUID,
        revision: AnswerRevisionRequest,
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
        idempotency_key: IdempotencyKey,
    ) -> ApplicationDetail:
        return service.revise_answer(candidate_id, application_id, revision, idempotency_key)

    @router.post("/{application_id}/start", response_model=ApplicationDetail)
    def start_application(
        application_id: UUID,
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
        idempotency_key: IdempotencyKey,
    ) -> ApplicationDetail:
        return service.start(candidate_id, application_id, idempotency_key)

    @router.post("/{application_id}/dry-run", response_model=ApplicationDetail)
    def dry_run_application(
        application_id: UUID,
        command: DryRunCommand,
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
        idempotency_key: IdempotencyKey,
    ) -> ApplicationDetail:
        return service.dry_run(candidate_id, application_id, command, idempotency_key)

    @router.post("/{application_id}/authorize", response_model=AuthorizationView)
    def authorize_application(
        application_id: UUID,
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
        idempotency_key: IdempotencyKey,
    ) -> AuthorizationView:
        return service.authorize(candidate_id, application_id, idempotency_key)

    @router.post("/{application_id}/controlled-authorize", response_model=AuthorizationView)
    def authorize_controlled_application(
        application_id: UUID,
        command: ControlledAuthorizationRequest,
        service: ApplicationServiceDependency,
        response: Response,
        candidate_id: Annotated[str, Query(min_length=1)],
        idempotency_key: IdempotencyKey,
    ) -> AuthorizationView:
        response.headers["Cache-Control"] = "no-store"
        return service.authorize_controlled(candidate_id, application_id, command, idempotency_key)

    @router.post(
        "/{application_id}/controlled-submissions",
        response_model=ControlledSubmissionExecutionView,
        status_code=202,
    )
    def queue_controlled_application_submission(
        application_id: UUID,
        command: ControlledSubmissionCommand,
        service: ApplicationServiceDependency,
        response: Response,
        candidate_id: Annotated[str, Query(min_length=1)],
        idempotency_key: IdempotencyKey,
    ) -> ControlledSubmissionExecutionView:
        response.headers["Cache-Control"] = "no-store"
        return service.queue_controlled_submission(
            candidate_id, application_id, command, idempotency_key
        )

    @router.get(
        "/{application_id}/controlled-submission",
        response_model=ControlledSubmissionExecutionView,
    )
    def get_controlled_application_submission(
        application_id: UUID,
        service: ApplicationServiceDependency,
        response: Response,
        candidate_id: Annotated[str, Query(min_length=1)],
    ) -> ControlledSubmissionExecutionView:
        response.headers["Cache-Control"] = "no-store"
        return service.get_controlled_submission(candidate_id, application_id)

    @router.post("/{application_id}/submit", response_model=SubmissionResultView)
    def submit_application(
        application_id: UUID,
        submission: SyntheticSubmissionRequest,
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
        idempotency_key: IdempotencyKey,
    ) -> SubmissionResultView:
        return service.submit_synthetic(candidate_id, application_id, submission, idempotency_key)

    @router.post("/{application_id}/withdraw", response_model=ApplicationDetail)
    def withdraw_application(
        application_id: UUID,
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
        idempotency_key: IdempotencyKey,
    ) -> ApplicationDetail:
        return service.withdraw(candidate_id, application_id, idempotency_key)

    @router.post("/{application_id}/prepare-interview", response_model=InterviewPreparationPackage)
    def prepare_interview(
        application_id: UUID,
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
        idempotency_key: IdempotencyKey,
    ) -> InterviewPreparationPackage:
        return service.prepare_interview(candidate_id, application_id, idempotency_key)

    @router.get("/{application_id}/archive", response_model=tuple[ArtifactView, ...])
    @router.get("/{application_id}/artifacts", response_model=tuple[ArtifactView, ...])
    def application_artifacts(
        application_id: UUID,
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
    ) -> tuple[ArtifactView, ...]:
        return service.list_artifacts(candidate_id, application_id)

    @router.get("/{application_id}/events", response_model=tuple[EventView, ...])
    def application_events(
        application_id: UUID,
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
    ) -> tuple[EventView, ...]:
        return service.get_application(candidate_id, application_id).events

    @router.get("/{application_id}/artifacts/{artifact_id}")
    def download_artifact(
        application_id: UUID,
        artifact_id: UUID,
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
    ) -> StreamingResponse:
        path = service.artifact_path(candidate_id, application_id, artifact_id)
        return StreamingResponse(
            service.artifact_chunks(candidate_id, application_id, artifact_id),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(path.name)}"},
        )

    return router


def _operations_router() -> APIRouter:
    router = APIRouter(prefix="/api", tags=["operations"])

    @router.get("/human-actions", response_model=tuple[HumanActionView, ...])
    def human_actions(
        service: ApplicationServiceDependency,
        response: Response,
        candidate_id: Annotated[str, Query(min_length=1)],
    ) -> tuple[HumanActionView, ...]:
        response.headers["Cache-Control"] = "no-store"
        return service.list_human_actions(candidate_id)

    @router.get("/human-actions/{action_id}", response_model=HumanActionView)
    def human_action(
        action_id: UUID,
        service: ApplicationServiceDependency,
        response: Response,
        candidate_id: Annotated[str, Query(min_length=1)],
    ) -> HumanActionView:
        response.headers["Cache-Control"] = "no-store"
        match = next(
            (
                item
                for item in service.list_human_actions(candidate_id)
                if item.action_id == action_id
            ),
            None,
        )
        if match is None:
            raise ApplicationNotFoundError("human action not found")
        return match

    @router.post("/human-actions/{action_id}/open-session", response_model=HumanActionView)
    def open_human_session(
        action_id: UUID,
        service: ApplicationServiceDependency,
        response: Response,
        candidate_id: Annotated[str, Query(min_length=1)],
        idempotency_key: IdempotencyKey,
    ) -> HumanActionView:
        response.headers["Cache-Control"] = "no-store"
        return service.open_human_session(candidate_id, action_id, idempotency_key)

    @router.post("/human-actions/{action_id}/complete", response_model=HumanActionView)
    def complete_human_action(
        action_id: UUID,
        service: ApplicationServiceDependency,
        response: Response,
        candidate_id: Annotated[str, Query(min_length=1)],
        idempotency_key: IdempotencyKey,
    ) -> HumanActionView:
        response.headers["Cache-Control"] = "no-store"
        return service.complete_human_action(candidate_id, action_id, idempotency_key)

    @router.post("/human-actions/{action_id}/cancel", response_model=HumanActionView)
    def cancel_human_action(
        action_id: UUID,
        service: ApplicationServiceDependency,
        response: Response,
        candidate_id: Annotated[str, Query(min_length=1)],
        idempotency_key: IdempotencyKey,
    ) -> HumanActionView:
        response.headers["Cache-Control"] = "no-store"
        return service.complete_human_action(candidate_id, action_id, idempotency_key, cancel=True)

    @router.get("/security-events", response_model=tuple[SecurityEventView, ...])
    def security_events(
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
    ) -> tuple[SecurityEventView, ...]:
        return service.list_security_events(candidate_id)

    @router.post("/security-events/{event_id}/resolve", response_model=SecurityEventView)
    def resolve_security_event(
        event_id: UUID,
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
        idempotency_key: IdempotencyKey,
    ) -> SecurityEventView:
        return service.resolve_security_event(candidate_id, event_id, idempotency_key)

    @router.get("/correspondence", response_model=tuple[CorrespondenceView, ...])
    def correspondence(
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
        application_id: UUID | None = None,
    ) -> tuple[CorrespondenceView, ...]:
        return service.list_correspondence(candidate_id, application_id)

    @router.post("/correspondence/ingest", response_model=CorrespondenceView)
    def ingest_correspondence(
        message: CorrespondenceIngestRequest,
        service: ApplicationServiceDependency,
        idempotency_key: IdempotencyKey,
    ) -> CorrespondenceView:
        return service.ingest_correspondence(message, idempotency_key)

    @router.get("/notifications", response_model=tuple[NotificationView, ...])
    def notifications(
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
    ) -> tuple[NotificationView, ...]:
        return service.list_notifications(candidate_id)

    @router.get("/settings", response_model=SettingsView)
    def settings(
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
    ) -> SettingsView:
        return service.get_settings(candidate_id)

    @router.patch("/settings", response_model=SettingsView)
    def update_settings(
        update: SettingsUpdate,
        service: ApplicationServiceDependency,
        idempotency_key: IdempotencyKey,
    ) -> SettingsView:
        return service.update_settings(update, idempotency_key)

    @router.post("/automation/emergency-stop", response_model=SettingsView)
    def emergency_stop(
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
        idempotency_key: IdempotencyKey,
    ) -> SettingsView:
        return service.emergency_stop(candidate_id, idempotency_key)

    @router.get("/analytics/overview", response_model=AnalyticsOverview)
    def analytics(
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
    ) -> AnalyticsOverview:
        return service.analytics(candidate_id)

    @router.get("/events/stream")
    def event_stream(
        service: ApplicationServiceDependency,
        candidate_id: Annotated[str, Query(min_length=1)],
    ) -> StreamingResponse:
        overview = service.analytics(candidate_id)

        def events() -> Iterator[str]:
            yield f"event: snapshot\ndata: {json.dumps(overview.model_dump(mode='json'))}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return router


def create_app(
    *,
    settings: Settings | None = None,
    candidate_service: CandidateService | None = None,
    job_service: JobService | None = None,
    scheduled_discovery_service: ScheduledDiscoveryService | None = None,
    candidate_lifecycle_service: CandidateLifecycleService | None = None,
    application_service: ApplicationService | None = None,
    health_checker: HealthChecker | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_environment()
    application = FastAPI(title="Career OS", version="0.2.0")
    resolved_candidate_service = candidate_service or CandidateService(
        resolved_settings.candidates_root
    )
    engine = build_engine(resolved_settings.database_url)
    session_factory = build_session_factory(engine)
    application.state.candidate_service = resolved_candidate_service
    source_verifier = ProviderJobSourceVerifier()
    resolved_job_service = job_service or JobService(
        session_factory, resolved_candidate_service, source_verifier
    )
    application.state.job_service = resolved_job_service
    application.state.scheduled_discovery_service = (
        scheduled_discovery_service
        or ScheduledDiscoveryService(
            session_factory,
            resolved_candidate_service,
            resolved_job_service,
            ProviderFeedClient(),
        )
    )
    application.state.candidate_lifecycle_service = (
        candidate_lifecycle_service
        or CandidateLifecycleService(
            session_factory, resolved_candidate_service, resolved_settings.runtime_root
        )
    )
    application.state.application_service = application_service or ApplicationService(
        session_factory,
        resolved_candidate_service,
        resolved_settings.runtime_root,
        source_verifier=source_verifier,
        controlled_submission_enabled=resolved_settings.controlled_submission_enabled,
    )
    application.state.health_checker = health_checker or HealthProbe(
        engine, resolved_settings.redis_url
    )
    secret = (
        resolved_settings.local_token_secret.encode("utf-8")
        if resolved_settings.local_token_secret
        else secrets.token_bytes(32)
    )
    if len(secret) < 32:
        raise ValueError("LOCAL_TOKEN_SECRET must contain at least 32 bytes")
    token_service = LocalTokenService(secret)
    application.state.token_service = token_service
    application.state.auth_required = resolved_settings.auth_required
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-CSRF-Token",
        ],
    )

    @application.middleware("http")
    async def candidate_authorization(request: Request, call_next: Any) -> Any:
        if request.method == "OPTIONS":
            return await call_next(request)
        destructive_deletion = request.method == "DELETE" and request.url.path.startswith(
            "/api/candidates/"
        )
        if (
            not application.state.auth_required and not destructive_deletion
        ) or request.url.path in {
            "/health",
            "/api/health",
            "/api/auth/local-session",
            "/docs",
            "/openapi.json",
        }:
            return await call_next(request)
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return _error("authentication_required", "A local session token is required.", 401)
        try:
            claims = token_service.verify_session(authorization.removeprefix("Bearer "))
            is_candidate_creation = (
                request.method == "POST" and request.url.path.rstrip("/") == "/api/candidates"
            )
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                csrf_token = request.headers.get("X-CSRF-Token")
                if not csrf_token:
                    return _error("csrf_required", "A CSRF token is required.", 403)
                token_service.verify_csrf(csrf_token, session_id=claims.session_id)
            candidate_ids: set[str] = set(request.query_params.getlist("candidate_id"))
            parts = request.url.path.strip("/").split("/")
            if len(parts) >= 3 and parts[:2] == ["api", "candidates"]:
                candidate_ids.add(parts[2])
            if request.method not in {"GET", "HEAD", "OPTIONS"} and not is_candidate_creation:
                body = await request.body()
                if body:
                    try:
                        payload = json.loads(body)
                    except ValueError:
                        payload = None
                    if isinstance(payload, dict) and isinstance(payload.get("candidate_id"), str):
                        candidate_ids.add(payload["candidate_id"])
            for candidate_id in candidate_ids:
                is_deletion_request = (
                    request.method == "DELETE"
                    and request.url.path.rstrip("/") == f"/api/candidates/{candidate_id}"
                )
                is_deletion_status = (
                    request.method == "GET"
                    and request.url.path.rstrip("/") == f"/api/candidates/{candidate_id}/deletion"
                )
                deleted = application.state.candidate_lifecycle_service.is_deleted(candidate_id)
                is_recovery = deleted and (is_deletion_request or is_deletion_status)
                if not is_recovery:
                    token_service.require_candidate(claims, candidate_id)
                if deleted and not is_recovery:
                    return _error(
                        "candidate_deleted", "Candidate data is no longer available.", 410
                    )
            request.state.session_claims = claims
        except (PermissionError, TokenValidationError) as exc:
            return _error("authorization_denied", str(exc), 403)
        return await call_next(request)

    # Decorator middleware is inserted at the front of Starlette's stack. Register the streaming
    # limiter afterwards so it is outermost and caps bytes before authorization calls body().
    application.add_middleware(
        _CandidateImportBodyLimitMiddleware,
        cv_max_bytes=_CV_IMPORT_MAX_REQUEST_BYTES,
        configuration_max_bytes=_CONFIGURATION_IMPORT_MAX_REQUEST_BYTES,
    )

    @application.post(
        "/api/auth/local-session",
        response_model=_LocalSessionResponse,
        tags=["authentication"],
    )
    def local_session(request: _LocalSessionRequest) -> _LocalSessionResponse:
        available = tuple(
            item.candidate_id for item in resolved_candidate_service.list_candidates()
        )
        candidate_ids = (
            (request.candidate_id,)
            if request.candidate_id is not None and request.candidate_id in available
            else available
        )
        if request.candidate_id is not None and request.candidate_id not in available:
            raise CandidateNotFoundError(f"candidate not found: {request.candidate_id}")
        session_id = secrets.token_urlsafe(18)
        return _LocalSessionResponse(
            session_token=token_service.issue_session(
                session_id=session_id,
                user_id="local-user",
                candidate_ids=candidate_ids,
                lifetime=timedelta(hours=8),
            ),
            csrf_token=token_service.issue_csrf(
                session_id=session_id,
                lifetime=timedelta(hours=8),
            ),
            candidate_ids=candidate_ids,
        )

    @application.exception_handler(CandidateNotFoundError)
    async def candidate_not_found(_request: Request, exc: CandidateNotFoundError) -> JSONResponse:
        return _error("candidate_not_found", str(exc), 404)

    @application.exception_handler(CandidateDeletionError)
    async def candidate_deletion_failed(
        _request: Request, exc: CandidateDeletionError
    ) -> JSONResponse:
        status_code = (
            404
            if exc.code == "deletion_not_found"
            else 409
            if exc.code in {"idempotency_conflict", "protected_candidate"}
            else 422
        )
        return _error(exc.code, str(exc), status_code)

    @application.exception_handler(IntegrityError)
    async def integrity_error(_request: Request, exc: IntegrityError) -> JSONResponse:
        if "candidate is deleted" in str(exc).casefold():
            return _error("candidate_deleted", "Candidate data is no longer available.", 410)
        return _error("command_conflict", "The command conflicts with persisted state.", 409)

    @application.exception_handler(JobNotFoundError)
    async def job_not_found(_request: Request, exc: JobNotFoundError) -> JSONResponse:
        return _error("job_not_found", str(exc), 404)

    @application.exception_handler(JobCommandConflictError)
    async def job_command_conflict(_request: Request, exc: JobCommandConflictError) -> JSONResponse:
        return _error("idempotency_conflict", str(exc), 409)

    @application.exception_handler(ScheduledDiscoveryError)
    async def scheduled_discovery_failed(
        _request: Request, exc: ScheduledDiscoveryError
    ) -> JSONResponse:
        return _error("scheduled_discovery_conflict", str(exc), 409)

    @application.exception_handler(ApplicationNotFoundError)
    async def application_not_found(
        _request: Request, exc: ApplicationNotFoundError
    ) -> JSONResponse:
        return _error("application_not_found", str(exc), 404)

    @application.exception_handler(ApplicationConflictError)
    async def application_conflict(
        _request: Request, exc: ApplicationConflictError
    ) -> JSONResponse:
        return _error("application_conflict", str(exc), 409)

    @application.exception_handler(CandidateIdempotencyError)
    async def candidate_idempotency_failed(
        _request: Request, exc: CandidateIdempotencyError
    ) -> JSONResponse:
        return _error("idempotency_conflict", str(exc), 409)

    @application.exception_handler(CandidateUpdateError)
    async def candidate_update_failed(_request: Request, exc: CandidateUpdateError) -> JSONResponse:
        return _error("candidate_update_invalid", str(exc), 422)

    @application.exception_handler(CandidatePortabilityError)
    async def candidate_portability_failed(
        _request: Request, exc: CandidatePortabilityError
    ) -> JSONResponse:
        status_code = 413 if exc.code == "candidate_import_too_large" else 422
        return _error(exc.code, str(exc), status_code)

    @application.exception_handler(CandidateConfigError)
    async def candidate_config_invalid(
        _request: Request, exc: CandidateConfigError
    ) -> JSONResponse:
        return _error("candidate_configuration_invalid", str(exc), 422)

    @application.exception_handler(RequestValidationError)
    async def request_validation_failed(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return _error(
            "request_validation_failed", "Request data did not match the API contract.", 422
        )

    @application.get("/health", tags=["operations"])
    def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/health", response_model=HealthReport, tags=["operations"])
    def health(checker: HealthCheckerDependency) -> HealthReport:
        return checker.check()

    application.include_router(_candidate_router())
    application.include_router(_job_router())
    application.include_router(_application_router())
    application.include_router(_operations_router())
    return application


app = create_app()
