from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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
    minimum_words: int | None = Field(default=None, ge=1)
    maximum_words: int | None = Field(default=None, ge=1)


class GeneratedAnswer(MaterialModel):
    question_key: str
    question: str
    answer: str
    approved_source_key: str | None
    evidence_ids: tuple[str, ...]
    supported: bool


class GenerationRequest(MaterialModel):
    candidate_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    candidate_name: str = Field(default="Candidate", min_length=1, max_length=200)
    application_id: UUID
    target: JobTarget
    requested_documents: tuple[DocumentKind, ...]
    approved_facts: tuple[ApprovedFact, ...]
    approved_answers: tuple[ApprovedAnswerFact, ...] = ()
    answer_prompts: tuple[AnswerPrompt, ...] = ()
    cv_template_id: Literal["technical_single_page", "technical_two_page"] = "technical_two_page"
    selected_experience_ids: tuple[str, ...] = ()
    selected_project_ids: tuple[str, ...] = ()
    cover_letter_experience_ids: tuple[str, ...] = ()
    cover_letter_project_ids: tuple[str, ...] = ()
    cover_letter_reason: str | None = None
    cover_letter_min_words: int = Field(default=50, ge=50, le=250)
    cover_letter_max_words: int = Field(default=400, ge=50, le=2000)

    @model_validator(mode="after")
    def cover_letter_word_range_is_valid(self) -> GenerationRequest:
        if self.cover_letter_max_words < self.cover_letter_min_words:
            raise ValueError("cover-letter maximum words must be at least minimum words")
        return self


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


class RenderValidationReport(MaterialModel):
    document_kind: DocumentKind
    document_version: int = Field(ge=1)
    template_id: str
    template_version: str
    renderer_version: Literal["deterministic_pdf_v2", "latex_pdf_v1"] = "deterministic_pdf_v2"
    compiler_version: Literal["restricted_latex_v1"] | None = None
    source_sha256: Sha256
    latex_sha256: Sha256 | None = None
    pdf_sha256: Sha256 | None = None
    extracted_text_sha256: Sha256 | None = None
    page_count: int = Field(ge=0)
    maximum_pages: int = Field(ge=1)
    extraction_matches: bool
    layout_overlap_count: int = Field(ge=0)
    valid: bool
    issues: tuple[ValidationIssue, ...] = ()

    @model_validator(mode="after")
    def latex_identity_matches_renderer(self) -> RenderValidationReport:
        if self.renderer_version == "latex_pdf_v1" and (
            self.compiler_version != "restricted_latex_v1" or self.latex_sha256 is None
        ):
            raise ValueError("LaTeX render reports require compiler and source identities")
        if self.renderer_version == "deterministic_pdf_v2" and (
            self.compiler_version is not None or self.latex_sha256 is not None
        ):
            raise ValueError("legacy render reports cannot declare LaTeX identities")
        return self


class AnswerReviewIdentity(MaterialModel):
    answer_id: UUID
    question_key: str = Field(min_length=1)
    version: int = Field(ge=1)
    sha256: Sha256
    candidate_snapshot_id: UUID


class MaterialReview(MaterialModel):
    decision: ReviewDecision
    semantic_review_passed: bool
    documents_supported: bool
    answers_supported: bool
    issues: tuple[ValidationIssue, ...] = ()
    render_reports: tuple[RenderValidationReport, ...] = ()
    answer_reports: tuple[AnswerReviewIdentity, ...] = ()


class DraftArtifactManifest(MaterialModel):
    schema_version: Literal["1.0"] = "1.0"
    candidate_id: str
    application_id: UUID
    kind: DocumentKind
    version: int = Field(ge=1)
    created_at: datetime
    payload_sha256: Sha256


class MaterialAgentProvenance(MaterialModel):
    """Immutable identity recorded for every material-generation boundary."""

    agent_version: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=128)


class DocumentGenerationAgent(Protocol):
    """Runtime material boundary; implementations have no browser or submission capability."""

    provenance: MaterialAgentProvenance

    def generate(self, request: GenerationRequest) -> GenerationResult: ...


class IndependentReviewAgent(Protocol):
    """Independent fail-closed review boundary over generated content and render evidence."""

    provenance: MaterialAgentProvenance

    def review(
        self,
        request: GenerationRequest,
        result: GenerationResult,
        render_reports: tuple[RenderValidationReport, ...] = (),
    ) -> MaterialReview: ...
