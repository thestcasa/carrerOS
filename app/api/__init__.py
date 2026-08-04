from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.candidates.loader import CandidateConfigError
from app.candidates.readiness import ReadinessReport
from app.candidates.service import (
    CandidateDetail,
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
from app.db import build_engine
from app.health import HealthChecker, HealthProbe, HealthReport


def _candidate_service(request: Request) -> CandidateService:
    return cast(CandidateService, request.app.state.candidate_service)


def _health_checker(request: Request) -> HealthChecker:
    return cast(HealthChecker, request.app.state.health_checker)


CandidateServiceDependency = Annotated[CandidateService, Depends(_candidate_service)]
HealthCheckerDependency = Annotated[HealthChecker, Depends(_health_checker)]


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

    @router.get("/{candidate_id}", response_model=CandidateDetail)
    def get_candidate(candidate_id: str, service: CandidateServiceDependency) -> CandidateDetail:
        return service.get_detail(candidate_id)

    @router.patch("/{candidate_id}", response_model=CandidateUpdateResult)
    def update_candidate(
        candidate_id: str,
        update: CandidateSectionUpdate,
        service: CandidateServiceDependency,
    ) -> CandidateUpdateResult:
        return service.update_section(candidate_id, update)

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
        candidate_id: str, service: CandidateServiceDependency
    ) -> CandidateSnapshot:
        return service.snapshot(candidate_id)

    return router


def create_app(
    *,
    settings: Settings | None = None,
    candidate_service: CandidateService | None = None,
    health_checker: HealthChecker | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_environment()
    application = FastAPI(title="Career OS", version="0.2.0")
    application.state.candidate_service = candidate_service or CandidateService(
        resolved_settings.candidates_root
    )
    application.state.health_checker = health_checker or HealthProbe(
        build_engine(resolved_settings.database_url), resolved_settings.redis_url
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type", "Idempotency-Key"],
    )

    @application.exception_handler(CandidateNotFoundError)
    async def candidate_not_found(_request: Request, exc: CandidateNotFoundError) -> JSONResponse:
        return _error("candidate_not_found", str(exc), 404)

    @application.exception_handler(CandidateUpdateError)
    async def candidate_update_failed(_request: Request, exc: CandidateUpdateError) -> JSONResponse:
        return _error("candidate_update_invalid", str(exc), 422)

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
    return application


app = create_app()
