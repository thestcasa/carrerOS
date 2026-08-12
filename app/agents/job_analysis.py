from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from pydantic import BaseModel

from app.agents.contracts import JobAnalysisRequest, JobAnalysisResponse, ScoringDimension
from app.jobs.scoring import (
    CandidateScoringContext,
    NormalizedJob,
    evaluate_job_with_context,
)


class JobAnalysisContractError(ValueError):
    """The runtime analysis request is incomplete, stale, or policy-inconsistent."""


def canonical_json(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def analysis_policy_sha256(context: CandidateScoringContext) -> str:
    return content_sha256(
        canonical_json(
            {
                "candidate_id": context.candidate_id,
                "profile_version": context.profile_version,
                "scoring_rules": context.scoring_rules.model_dump(mode="json"),
            }
        )
    )


@dataclass(frozen=True, slots=True)
class DeterministicJobAnalysisAgent:
    """Stateless production analysis boundary with no tools or submission capability."""

    provider: str = "local"
    model: str = "deterministic-scoring-v1"
    prompt_version: str = "1.0"

    def analyze(self, request: JobAnalysisRequest) -> JobAnalysisResponse:
        required_identity = (
            request.job_id,
            request.candidate_profile_version,
            request.candidate_snapshot_sha256,
            request.job_version,
            request.job_payload_sha256,
            request.job_snapshot_sha256,
            request.policy_sha256,
        )
        if any(value is None for value in required_identity):
            raise JobAnalysisContractError("runtime analysis identity is incomplete")
        try:
            context = CandidateScoringContext.model_validate_json(request.candidate_snapshot_json)
            job = NormalizedJob.model_validate_json(request.job_snapshot_json)
        except ValueError as exc:
            raise JobAnalysisContractError("runtime analysis snapshot is invalid") from exc
        expected_weights = tuple(
            (name, float(weight)) for name, weight in context.scoring_rules.weights.items()
        )
        mismatches = [
            name
            for name, matches in (
                ("candidate_id", context.candidate_id == request.candidate_id),
                ("profile_version", context.profile_version == request.candidate_profile_version),
                ("job_id", job.job_id == request.job_id),
                (
                    "candidate_snapshot_sha256",
                    content_sha256(request.candidate_snapshot_json)
                    == request.candidate_snapshot_sha256,
                ),
                (
                    "job_snapshot_sha256",
                    content_sha256(request.job_snapshot_json) == request.job_snapshot_sha256,
                ),
                ("policy_sha256", analysis_policy_sha256(context) == request.policy_sha256),
                (
                    "application_threshold",
                    request.application_threshold == context.scoring_rules.application_threshold,
                ),
                ("scoring_weights", request.scoring_weights == expected_weights),
            )
            if not matches
        ]
        if mismatches:
            raise JobAnalysisContractError(
                "runtime analysis policy identity does not match: " + ", ".join(mismatches)
            )

        evaluation = evaluate_job_with_context(job, context)
        dimensions = tuple(
            ScoringDimension(
                name=item.name,
                score=item.score,
                weight=item.weight,
                contribution=item.contribution,
                rationale=item.explanation,
                evidence_ids=item.evidence,
            )
            for item in evaluation.dimensions
        )
        return JobAnalysisResponse(
            request_id=request.request_id,
            candidate_id=request.candidate_id,
            total_score=evaluation.total_score,
            meets_threshold=evaluation.total_score >= request.application_threshold,
            dimensions=dimensions,
            warnings=tuple(f"hard_blocker:{item}" for item in evaluation.hard_blockers),
            job_id=request.job_id,
            scoring_version=request.scoring_version,
            candidate_snapshot_sha256=request.candidate_snapshot_sha256,
            job_payload_sha256=request.job_payload_sha256,
            job_snapshot_sha256=request.job_snapshot_sha256,
            policy_sha256=request.policy_sha256,
            application_threshold=request.application_threshold,
            provider=self.provider,
            model=self.model,
            prompt_version=self.prompt_version,
        )
