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
        analysis = self._analysis_agent.analyze(
            JobAnalysisRequest(
                request_id=uuid4(),
                candidate_id=candidate_id,
                candidate_snapshot_json=candidate_snapshot_json,
                job_snapshot_json=job_snapshot_json,
                scoring_version=scoring_version,
                application_threshold=application_threshold,
                scoring_weights=scoring_weights,
            )
        )
        generation = self._document_agent.generate(
            DocumentGenerationRequest(
                request_id=uuid4(),
                candidate_id=candidate_id,
                candidate_snapshot_json=candidate_snapshot_json,
                job_snapshot_json=job_snapshot_json,
                analysis=analysis,
                requested_documents=requested_documents,
                approved_answers_json=approved_answers_json,
                document_rules_json=document_rules_json,
            )
        )
        review = self._review_agent.review(
            IndependentReviewRequest(
                request_id=uuid4(),
                candidate_id=candidate_id,
                candidate_snapshot_json=candidate_snapshot_json,
                job_snapshot_json=job_snapshot_json,
                analysis=analysis,
                generation=generation,
                policy_snapshot_json=policy_snapshot_json,
            )
        )
        return PreparationResult(analysis=analysis, generation=generation, review=review)
