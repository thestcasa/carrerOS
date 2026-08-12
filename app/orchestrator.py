from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.agents.contracts import (
    DocumentGenerationAgent,
    DocumentGenerationRequest,
    DocumentGenerationResponse,
    IndependentReviewAgent,
    IndependentReviewRequest,
    IndependentReviewResponse,
    JobAnalysisAgent,
    JobAnalysisRequest,
    JobAnalysisResponse,
)
from app.domain.enums import DocumentKind


@dataclass(frozen=True, slots=True)
class PreparationResult:
    analysis: JobAnalysisResponse
    generation: DocumentGenerationResponse
    review: IndependentReviewResponse


class AgentResponseCorrelationError(RuntimeError):
    """Raised when an isolated agent returns a response for another request or candidate."""


def _validate_response_correlation(
    *,
    stage: str,
    request: JobAnalysisRequest | DocumentGenerationRequest | IndependentReviewRequest,
    response: JobAnalysisResponse | DocumentGenerationResponse | IndependentReviewResponse,
) -> None:
    mismatches: list[str] = []
    if response.request_id != request.request_id:
        mismatches.append("request_id")
    if response.candidate_id != request.candidate_id:
        mismatches.append("candidate_id")
    if mismatches:
        fields = ", ".join(mismatches)
        raise AgentResponseCorrelationError(
            f"{stage} agent response correlation failed for: {fields}"
        )


class ApplicationOrchestrator:
    """Sequences three isolated workers; it has no submission capability."""

    def __init__(
        self,
        analysis_agent: JobAnalysisAgent,
        document_agent: DocumentGenerationAgent,
        review_agent: IndependentReviewAgent,
    ) -> None:
        self._analysis_agent = analysis_agent
        self._document_agent = document_agent
        self._review_agent = review_agent

    def prepare(
        self,
        *,
        candidate_id: str,
        candidate_snapshot_json: str,
        job_snapshot_json: str,
        approved_answers_json: str,
        document_rules_json: str,
        policy_snapshot_json: str,
        scoring_version: int,
        application_threshold: int,
        scoring_weights: tuple[tuple[str, float], ...],
        requested_documents: tuple[DocumentKind, ...],
    ) -> PreparationResult:
        analysis_request = JobAnalysisRequest(
            request_id=uuid4(),
            candidate_id=candidate_id,
            candidate_snapshot_json=candidate_snapshot_json,
            job_snapshot_json=job_snapshot_json,
            scoring_version=scoring_version,
            application_threshold=application_threshold,
            scoring_weights=scoring_weights,
        )
        analysis = self._analysis_agent.analyze(analysis_request)
        _validate_response_correlation(
            stage="analysis", request=analysis_request, response=analysis
        )

        generation_request = DocumentGenerationRequest(
            request_id=uuid4(),
            candidate_id=candidate_id,
            candidate_snapshot_json=candidate_snapshot_json,
            job_snapshot_json=job_snapshot_json,
            analysis=analysis,
            requested_documents=requested_documents,
            approved_answers_json=approved_answers_json,
            document_rules_json=document_rules_json,
        )
        generation = self._document_agent.generate(generation_request)
        _validate_response_correlation(
            stage="document generation", request=generation_request, response=generation
        )

        review_request = IndependentReviewRequest(
            request_id=uuid4(),
            candidate_id=candidate_id,
            candidate_snapshot_json=candidate_snapshot_json,
            job_snapshot_json=job_snapshot_json,
            analysis=analysis,
            generation=generation,
            policy_snapshot_json=policy_snapshot_json,
        )
        review = self._review_agent.review(review_request)
        _validate_response_correlation(
            stage="independent review", request=review_request, response=review
        )
        return PreparationResult(analysis=analysis, generation=generation, review=review)
