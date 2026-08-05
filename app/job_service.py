from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.candidates.service import CandidateService
from app.discovery.adapters import AshbyAdapter, GreenhouseAdapter, LeverAdapter
from app.discovery.contracts import JobPayloadAdapter, NormalizedJob
from app.discovery.deduplication import semantic_description_fingerprint
from app.discovery.security import scan_prompt_injection
from app.domain.models import (
    CandidateDiscoveryCommand,
    CandidateJobCommand,
    CandidateJobDecision,
    CandidateJobScore,
    GlobalJob,
    JobVersion,
    SecurityEvent,
)
from app.jobs.scoring import NormalizedJob as ScoringJob
from app.jobs.scoring import evaluate_job


class JobServiceError(ValueError):
    pass


class JobNotFoundError(JobServiceError):
    pass


class JobCommandConflictError(JobServiceError):
    pass


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DiscoveryRequest(_Contract):
    candidate_id: str = Field(min_length=1)
    platform: Literal["greenhouse", "lever", "ashby"]
    company: str = Field(min_length=1)
    company_domain: str = Field(min_length=1)
    payloads: tuple[dict[str, Any], ...]


class DiscoveryResult(_Contract):
    discovered: int
    unchanged: int
    job_ids: tuple[UUID, ...]


class JobView(_Contract):
    job_id: UUID
    candidate_id: str
    company: str
    title: str
    location: str | None
    remote_policy: str | None
    source: str
    source_url: str
    ats_platform: str | None
    posted_at: datetime | None
    verified_open_at: datetime | None
    salary_display: str | None
    role_category: str | None
    score: int | None = None
    state: str = "discovered"
    hard_blockers: tuple[str, ...] = ()
    possible_duplicate: bool = False
    stale: bool = False
    description_raw: str
    description_normalized: str
    source_verified: bool
    source_trust_level: str
    classification_confidence: int | None = None
    proposed_action: str = "review"
    required_skills: tuple[str, ...] = ()
    preferred_skills: tuple[str, ...] = ()
    requirements: tuple[dict[str, Any], ...] = ()
    score_dimensions: tuple[dict[str, Any], ...] = ()
    bonuses: tuple[dict[str, Any], ...] = ()
    penalties: tuple[dict[str, Any], ...] = ()
    salary_evidence: str | None = None
    salary_confidence: int | None = None
    selected_experience: tuple[str, ...] = ()
    selected_projects: tuple[str, ...] = ()
    security_findings: tuple[dict[str, str], ...] = ()


class JobService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        candidate_service: CandidateService,
    ) -> None:
        self._sessions = session_factory
        self._candidates = candidate_service
        self._adapters: dict[str, JobPayloadAdapter] = {
            "greenhouse": GreenhouseAdapter(),
            "lever": LeverAdapter(),
            "ashby": AshbyAdapter(),
        }

    def discover(
        self, request: DiscoveryRequest, idempotency_key: str | None = None
    ) -> DiscoveryResult:
        self._candidates.get_config(request.candidate_id)
        request_json = json.dumps(
            request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        request_sha256 = hashlib.sha256(request_json.encode()).hexdigest()
        command_key = idempotency_key or f"content-{request_sha256}"
        adapter = self._adapters[request.platform]
        discovered = 0
        unchanged = 0
        job_ids: list[UUID] = []
        with self._sessions.begin() as session:
            existing_command = session.scalar(
                select(CandidateDiscoveryCommand).where(
                    CandidateDiscoveryCommand.candidate_id == request.candidate_id,
                    CandidateDiscoveryCommand.idempotency_key == command_key,
                )
            )
            if existing_command is not None:
                if existing_command.request_sha256 != request_sha256:
                    raise JobCommandConflictError(
                        "idempotency key was already used for different discovery input"
                    )
                return DiscoveryResult.model_validate(existing_command.result)
            for payload in request.payloads:
                normalized = adapter.parse(
                    payload,
                    company=request.company,
                    company_domain=request.company_domain,
                )
                job, changed = self._upsert(session, normalized)
                job_ids.append(job.id)
                discovered += int(changed)
                unchanged += int(not changed)
                if changed:
                    for finding in job.security_findings:
                        session.add(
                            SecurityEvent(
                                candidate_id=request.candidate_id,
                                application_id=None,
                                category="prompt_injection",
                                severity="blocking",
                                details={
                                    "job_id": str(job.id),
                                    "code": finding["code"],
                                    "excerpt": finding["excerpt"],
                                },
                            )
                        )
            result = DiscoveryResult(
                discovered=discovered, unchanged=unchanged, job_ids=tuple(job_ids)
            )
            session.add(
                CandidateDiscoveryCommand(
                    candidate_id=request.candidate_id,
                    idempotency_key=command_key,
                    request_sha256=request_sha256,
                    result=result.model_dump(mode="json"),
                )
            )
            return result

    def list_jobs(self, candidate_id: str) -> tuple[JobView, ...]:
        self._candidates.get_config(candidate_id)
        with self._sessions() as session:
            jobs = session.scalars(select(GlobalJob).order_by(GlobalJob.first_seen_at.desc())).all()
            return tuple(self._view(session, job, candidate_id) for job in jobs)

    def get_job(self, candidate_id: str, job_id: UUID) -> JobView:
        self._candidates.get_config(candidate_id)
        with self._sessions() as session:
            job = session.get(GlobalJob, job_id)
            if job is None:
                raise JobNotFoundError(f"job not found: {job_id}")
            return self._view(session, job, candidate_id)

    def analyze(self, candidate_id: str, job_id: UUID, idempotency_key: str) -> JobView:
        config = self._candidates.get_config(candidate_id)
        with self._sessions.begin() as session:
            job = session.get(GlobalJob, job_id)
            if job is None:
                raise JobNotFoundError(f"job not found: {job_id}")
            if job.security_findings:
                return self._record_decision(
                    session, candidate_id, job, "blocked", "analyze", idempotency_key
                )
            replay = self._command_replay(session, candidate_id, job_id, "analyze", idempotency_key)
            if replay:
                return self._view(session, job, candidate_id)
            evaluation = evaluate_job(
                ScoringJob(
                    job_id=str(job.id),
                    company=job.company,
                    title=job.title,
                    description=job.description_normalized or job.description,
                    location=job.location,
                    work_mode=job.remote_policy,
                    employment_type=job.employment_type,
                    required_skills=tuple(job.required_skills),
                    preferred_skills=tuple(job.preferred_skills),
                    salary_min=int(job.salary_min) if job.salary_min is not None else None,
                    salary_max=int(job.salary_max) if job.salary_max is not None else None,
                    salary_currency=job.salary_currency,
                ),
                config,
            )
            latest = session.scalar(
                select(func.max(CandidateJobScore.scoring_version)).where(
                    CandidateJobScore.candidate_id == candidate_id,
                    CandidateJobScore.job_id == job_id,
                )
            )
            session.add(
                CandidateJobScore(
                    candidate_id=candidate_id,
                    job_id=job_id,
                    scoring_version=(latest or 0) + 1,
                    total_score=Decimal(evaluation.total_score),
                    dimensions={
                        "items": [item.model_dump(mode="json") for item in evaluation.dimensions]
                    },
                    rationale={
                        "classification": evaluation.classification.value,
                        "proposed_action": evaluation.proposed_action,
                        "hard_blockers": list(evaluation.hard_blockers),
                        "evidence": list(evaluation.evidence),
                    },
                    meets_threshold=evaluation.proposed_action == "prepare",
                )
            )
            decision = session.scalar(
                select(CandidateJobDecision).where(
                    CandidateJobDecision.candidate_id == candidate_id,
                    CandidateJobDecision.job_id == job_id,
                )
            )
            if decision is None:
                session.add(
                    CandidateJobDecision(
                        candidate_id=candidate_id,
                        job_id=job_id,
                        state="scored",
                    )
                )
            else:
                decision.state = "scored"
            session.add(
                CandidateJobCommand(
                    candidate_id=candidate_id,
                    job_id=job_id,
                    command="analyze",
                    idempotency_key=idempotency_key,
                )
            )
        return self.get_job(candidate_id, job_id)

    def command(
        self,
        candidate_id: str,
        job_id: UUID,
        command: Literal["verify", "shortlist", "skip"],
        idempotency_key: str,
    ) -> JobView:
        self._candidates.get_config(candidate_id)
        with self._sessions.begin() as session:
            job = session.get(GlobalJob, job_id)
            if job is None:
                raise JobNotFoundError(f"job not found: {job_id}")
            state = {"verify": "discovered", "shortlist": "shortlisted", "skip": "ignored"}[command]
            return self._record_decision(
                session, candidate_id, job, state, command, idempotency_key
            )

    def _command_replay(
        self,
        session: Session,
        candidate_id: str,
        job_id: UUID,
        command: str,
        idempotency_key: str,
    ) -> bool:
        receipt = session.scalar(
            select(CandidateJobCommand).where(
                CandidateJobCommand.candidate_id == candidate_id,
                CandidateJobCommand.idempotency_key == idempotency_key,
            )
        )
        if receipt is None:
            return False
        if receipt.job_id != job_id or receipt.command != command:
            raise JobCommandConflictError("idempotency key was already used for different input")
        return True

    def _record_decision(
        self,
        session: Session,
        candidate_id: str,
        job: GlobalJob,
        state: str,
        command: str,
        idempotency_key: str,
    ) -> JobView:
        if self._command_replay(session, candidate_id, job.id, command, idempotency_key):
            return self._view(session, job, candidate_id)
        decision = session.scalar(
            select(CandidateJobDecision).where(
                CandidateJobDecision.candidate_id == candidate_id,
                CandidateJobDecision.job_id == job.id,
            )
        )
        verified_at = datetime.now(UTC) if command == "verify" else None
        if decision is None:
            decision = CandidateJobDecision(
                candidate_id=candidate_id,
                job_id=job.id,
                state=state,
                verified_open_at=verified_at,
            )
            session.add(decision)
        else:
            decision.state = state
            if verified_at is not None:
                decision.verified_open_at = verified_at
        session.add(
            CandidateJobCommand(
                candidate_id=candidate_id,
                job_id=job.id,
                command=command,
                idempotency_key=idempotency_key,
            )
        )
        if verified_at is not None:
            job.verified_open_at = verified_at
        session.flush()
        return self._view(session, job, candidate_id)

    def _upsert(self, session: Session, normalized: NormalizedJob) -> tuple[GlobalJob, bool]:
        job = session.scalar(
            select(GlobalJob).where(
                GlobalJob.source == normalized.source,
                GlobalJob.external_id == normalized.external_job_id,
            )
        )
        canonical = normalized.model_dump(mode="json")
        version_identity = {
            key: value for key, value in canonical.items() if key != "discovered_at"
        }
        payload_sha = hashlib.sha256(
            json.dumps(version_identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if job is not None:
            existing = session.scalar(
                select(JobVersion.id).where(
                    JobVersion.job_id == job.id, JobVersion.payload_sha256 == payload_sha
                )
            )
            if existing is not None:
                return job, False
        findings = scan_prompt_injection(normalized.description_normalized)
        values: dict[str, Any] = {
            "source": normalized.source,
            "external_id": normalized.external_job_id,
            "requisition_id": normalized.requisition_id,
            "company": normalized.company,
            "company_domain": normalized.company_domain,
            "title": normalized.title,
            "normalized_title": normalized.normalized_title,
            "location": normalized.location,
            "remote_policy": normalized.remote_policy,
            "employment_type": normalized.employment_type,
            "description": normalized.description_raw,
            "description_normalized": normalized.description_normalized,
            "url": str(normalized.source_url),
            "application_url": str(normalized.application_url),
            "ats_platform": normalized.ats_platform,
            "source_trust_level": normalized.source_trust_level.value,
            "posted_at": normalized.posted_at,
            "semantic_fingerprint": semantic_description_fingerprint(
                normalized.description_normalized
            ),
            "security_findings": [
                {"code": finding.code, "excerpt": finding.excerpt} for finding in findings
            ],
            "raw_payload": normalized.raw_payload,
        }
        if job is None:
            job = GlobalJob(**values)
            session.add(job)
            session.flush()
            version = 1
        else:
            for key, value in values.items():
                setattr(job, key, value)
            version = (
                int(
                    session.scalar(
                        select(func.max(JobVersion.version)).where(JobVersion.job_id == job.id)
                    )
                    or 0
                )
                + 1
            )
        session.add(
            JobVersion(
                job_id=job.id,
                version=version,
                payload_sha256=payload_sha,
                normalized_payload=canonical,
                source_payload=normalized.raw_payload,
            )
        )
        return job, True

    def _view(self, session: Session, job: GlobalJob, candidate_id: str) -> JobView:
        score = session.scalar(
            select(CandidateJobScore)
            .where(
                CandidateJobScore.candidate_id == candidate_id,
                CandidateJobScore.job_id == job.id,
            )
            .order_by(CandidateJobScore.scoring_version.desc())
            .limit(1)
        )
        rationale = score.rationale if score is not None else {}
        dimensions = score.dimensions.get("items", []) if score is not None else []
        classification = rationale.get("classification")
        decision = session.scalar(
            select(CandidateJobDecision).where(
                CandidateJobDecision.candidate_id == candidate_id,
                CandidateJobDecision.job_id == job.id,
            )
        )
        return JobView(
            job_id=job.id,
            candidate_id=candidate_id,
            company=job.company,
            title=job.title,
            location=job.location,
            remote_policy=job.remote_policy,
            source=job.source,
            source_url=job.url,
            ats_platform=job.ats_platform,
            posted_at=job.posted_at,
            verified_open_at=job.verified_open_at,
            salary_display=(
                f"{job.salary_currency} {job.salary_min or '?'}-{job.salary_max or '?'}"
                if job.salary_currency
                else None
            ),
            role_category=classification if isinstance(classification, str) else None,
            score=int(score.total_score) if score is not None else None,
            state=decision.state
            if decision is not None
            else ("blocked" if job.security_findings else "discovered"),
            hard_blockers=tuple(rationale.get("hard_blockers", []))
            + (("security_review_required",) if job.security_findings else ()),
            description_raw=job.description,
            description_normalized=job.description_normalized or job.description,
            source_verified=job.source_trust_level != "unverified",
            source_trust_level=job.source_trust_level,
            proposed_action=rationale.get("proposed_action", "review"),
            required_skills=tuple(job.required_skills),
            preferred_skills=tuple(job.preferred_skills),
            score_dimensions=tuple(
                {
                    "name": item["name"],
                    "points": int(Decimal(str(item["contribution"]))),
                    "explanation": item["explanation"],
                }
                for item in dimensions
            ),
            security_findings=tuple(
                {
                    "severity": "blocking",
                    "code": finding["code"],
                    "explanation": finding["excerpt"],
                }
                for finding in job.security_findings
            ),
        )
