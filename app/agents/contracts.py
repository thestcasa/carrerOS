from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import DocumentKind, ReviewDecision


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScoringDimension(ContractModel):
    name: str = Field(min_length=1, max_length=64)
    score: int = Field(ge=0, le=100)
    weight: Decimal = Field(ge=0, le=1)
    contribution: Decimal = Field(ge=0, le=100)
    rationale: str = Field(min_length=1, max_length=1000)
    evidence_ids: tuple[str, ...] = ()


class JobAnalysisRequest(ContractModel):
    request_id: UUID
    candidate_id: str = Field(min_length=1)
    candidate_snapshot_json: str = Field(min_length=2)
    job_snapshot_json: str = Field(min_length=2)
    scoring_version: int = Field(ge=1)
    application_threshold: int = Field(ge=0, le=100)
    scoring_weights: tuple[tuple[str, float], ...]
    job_id: str | None = Field(default=None, min_length=1, max_length=128)
    candidate_profile_version: str | None = Field(default=None, pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    candidate_snapshot_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    job_version: int | None = Field(default=None, ge=1)
    job_payload_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    job_snapshot_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    policy_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class JobAnalysisResponse(ContractModel):
    request_id: UUID
    candidate_id: str
    total_score: int = Field(ge=0, le=100)
    meets_threshold: bool
    dimensions: tuple[ScoringDimension, ...] = Field(min_length=1, max_length=32)
    warnings: tuple[str, ...] = ()
    job_id: str | None = Field(default=None, min_length=1, max_length=128)
    scoring_version: int | None = Field(default=None, ge=1)
    candidate_snapshot_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    job_payload_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    job_snapshot_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    policy_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    application_threshold: int | None = Field(default=None, ge=0, le=100)
    provider: str = Field(default="test", min_length=1, max_length=64)
    model: str = Field(default="deterministic-fake", min_length=1, max_length=128)
    prompt_version: str = Field(default="1.0", min_length=1, max_length=32)

    @model_validator(mode="after")
    def analysis_is_internally_consistent(self) -> JobAnalysisResponse:
        names = [dimension.name for dimension in self.dimensions]
        if len(names) != len(set(names)):
            raise ValueError("analysis dimensions must be unique")
        total = sum((item.contribution for item in self.dimensions), Decimal(0))
        recomputed = int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if recomputed != self.total_score:
            raise ValueError("analysis total does not match dimension contributions")
        if self.application_threshold is not None and self.meets_threshold != (
            self.total_score >= self.application_threshold
        ):
            raise ValueError("analysis threshold result is inconsistent")
        return self


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
