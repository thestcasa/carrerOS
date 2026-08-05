from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.domain.enums import DocumentKind, ReviewDecision

Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class MaterialModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class JobTarget(MaterialModel):
    company: str = Field(min_length=1)
    title: str = Field(min_length=1)


class ApprovedFact(MaterialModel):
    fact_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    text: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    document_kinds: tuple[DocumentKind, ...] = (
        DocumentKind.CV,
        DocumentKind.COVER_LETTER,
    )


class ApprovedAnswerFact(MaterialModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    question_pattern: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()


class AnswerPrompt(MaterialModel):
    question_key: str = Field(min_length=1)
    question: str = Field(min_length=1)


class Claim(MaterialModel):
    text: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)


class GeneratedDocument(MaterialModel):
    kind: DocumentKind
    company: str = Field(min_length=1)
    content: str = Field(min_length=1)
    claims: tuple[Claim, ...]
    content_sha256: Sha256


class GeneratedAnswer(MaterialModel):
    question_key: str
    question: str
    answer: str
    approved_source_key: str | None
    evidence_ids: tuple[str, ...]
    supported: bool


class GenerationRequest(MaterialModel):
    candidate_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    application_id: UUID
    target: JobTarget
    requested_documents: tuple[DocumentKind, ...]
    approved_facts: tuple[ApprovedFact, ...]
    approved_answers: tuple[ApprovedAnswerFact, ...] = ()
    answer_prompts: tuple[AnswerPrompt, ...] = ()


class GenerationResult(MaterialModel):
    candidate_id: str
    application_id: UUID
    target: JobTarget
    documents: tuple[GeneratedDocument, ...]
    answers: tuple[GeneratedAnswer, ...]


class ValidationIssue(MaterialModel):
    code: str
    severity: Literal["warning", "error"]
    message: str
    document_kind: DocumentKind | None = None


class ValidationReport(MaterialModel):
    valid: bool
    issues: tuple[ValidationIssue, ...] = ()


class MaterialReview(MaterialModel):
    decision: ReviewDecision
    semantic_review_passed: bool
    documents_supported: bool
    answers_supported: bool
    issues: tuple[ValidationIssue, ...] = ()


class DraftArtifactManifest(MaterialModel):
    schema_version: Literal["1.0"] = "1.0"
    candidate_id: str
    application_id: UUID
    kind: DocumentKind
    version: int = Field(ge=1)
    created_at: datetime
    payload_sha256: Sha256
