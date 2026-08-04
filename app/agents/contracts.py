from __future__ import annotations

from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import DocumentKind, ReviewDecision


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScoringDimension(ContractModel):
    name: str = Field(min_length=1)
    score: int = Field(ge=0, le=100)
    weight: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()


class JobAnalysisRequest(ContractModel):
    request_id: UUID
    candidate_id: str = Field(min_length=1)
    candidate_snapshot_json: str = Field(min_length=2)
    job_snapshot_json: str = Field(min_length=2)
    scoring_version: int = Field(ge=1)
    application_threshold: int = Field(ge=0, le=100)
    scoring_weights: tuple[tuple[str, float], ...]


class JobAnalysisResponse(ContractModel):
    request_id: UUID
    candidate_id: str
    total_score: int = Field(ge=0, le=100)
    meets_threshold: bool
    dimensions: tuple[ScoringDimension, ...]
    warnings: tuple[str, ...] = ()


class DocumentGenerationRequest(ContractModel):
    request_id: UUID
    candidate_id: str = Field(min_length=1)
    candidate_snapshot_json: str = Field(min_length=2)
    job_snapshot_json: str = Field(min_length=2)
    analysis: JobAnalysisResponse
    requested_documents: tuple[DocumentKind, ...]
    approved_answers_json: str = Field(min_length=2)
    document_rules_json: str = Field(min_length=2)


class GeneratedDocument(ContractModel):
    kind: DocumentKind
    content: str = Field(min_length=1)
    evidence_ids: tuple[str, ...]
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ProposedAnswer(ContractModel):
    question_key: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    approved_source_key: str | None = None
    evidence_ids: tuple[str, ...] = ()
    supported: bool


class DocumentGenerationResponse(ContractModel):
    request_id: UUID
    candidate_id: str
    documents: tuple[GeneratedDocument, ...]
    answers: tuple[ProposedAnswer, ...]
    warnings: tuple[str, ...] = ()


class IndependentReviewRequest(ContractModel):
    request_id: UUID
    candidate_id: str = Field(min_length=1)
    candidate_snapshot_json: str = Field(min_length=2)
    job_snapshot_json: str = Field(min_length=2)
    analysis: JobAnalysisResponse
    generation: DocumentGenerationResponse
    policy_snapshot_json: str = Field(min_length=2)


class ReviewIssue(ContractModel):
    code: str = Field(min_length=1)
    severity: Literal["warning", "error"]
    message: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()


class IndependentReviewResponse(ContractModel):
    request_id: UUID
    candidate_id: str
    decision: ReviewDecision
    semantic_review_passed: bool
    documents_supported: bool
    answers_supported: bool
    issues: tuple[ReviewIssue, ...] = ()


class JobAnalysisAgent(Protocol):
    def analyze(self, request: JobAnalysisRequest) -> JobAnalysisResponse: ...


class DocumentGenerationAgent(Protocol):
    def generate(self, request: DocumentGenerationRequest) -> DocumentGenerationResponse: ...


class IndependentReviewAgent(Protocol):
    def review(self, request: IndependentReviewRequest) -> IndependentReviewResponse: ...
