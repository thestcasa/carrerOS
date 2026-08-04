from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.agents.contracts import (
    DocumentGenerationRequest,
    DocumentGenerationResponse,
    GeneratedDocument,
    IndependentReviewRequest,
    IndependentReviewResponse,
    JobAnalysisRequest,
    JobAnalysisResponse,
    ProposedAnswer,
    ReviewIssue,
    ScoringDimension,
)
from app.domain.enums import ReviewDecision


@dataclass(frozen=True, slots=True)
class FakeJobAnalysisAgent:
    score: int = 85
    evidence_ids: tuple[str, ...] = ()

    def analyze(self, request: JobAnalysisRequest) -> JobAnalysisResponse:
        dimensions = tuple(
            ScoringDimension(
                name=name,
                score=self.score,
                weight=weight,
                rationale=f"Deterministic fake score for {name}.",
                evidence_ids=self.evidence_ids,
            )
            for name, weight in request.scoring_weights
        )
        return JobAnalysisResponse(
            request_id=request.request_id,
            candidate_id=request.candidate_id,
            total_score=self.score,
            meets_threshold=self.score >= request.application_threshold,
            dimensions=dimensions,
        )


@dataclass(frozen=True, slots=True)
class FakeDocumentGenerationAgent:
    evidence_ids: tuple[str, ...] = ()
    answers: tuple[ProposedAnswer, ...] = ()

    def generate(self, request: DocumentGenerationRequest) -> DocumentGenerationResponse:
        documents: list[GeneratedDocument] = []
        for kind in request.requested_documents:
            content = f"Fictional deterministic {kind.value} for {request.candidate_id}."
            documents.append(
                GeneratedDocument(
                    kind=kind,
                    content=content,
                    evidence_ids=self.evidence_ids,
                    content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                )
            )
        return DocumentGenerationResponse(
            request_id=request.request_id,
            candidate_id=request.candidate_id,
            documents=tuple(documents),
            answers=self.answers,
        )


@dataclass(frozen=True, slots=True)
class FakeIndependentReviewAgent:
    passes: bool = True

    def review(self, request: IndependentReviewRequest) -> IndependentReviewResponse:
        generation_supported = all(answer.supported for answer in request.generation.answers)
        passed = self.passes and generation_supported
        issues: tuple[ReviewIssue, ...] = ()
        if not passed:
            issues = (
                ReviewIssue(
                    code="semantic_support_failed",
                    severity="error",
                    message="The deterministic fake reviewer rejected semantic support.",
                ),
            )
        return IndependentReviewResponse(
            request_id=request.request_id,
            candidate_id=request.candidate_id,
            decision=ReviewDecision.PASS if passed else ReviewDecision.FAIL,
            semantic_review_passed=passed,
            documents_supported=passed,
            answers_supported=passed,
            issues=issues,
        )
