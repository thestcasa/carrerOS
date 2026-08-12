from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CorrespondenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CorrespondenceKind(StrEnum):
    CONFIRMATION = "confirmation"
    REJECTION = "rejection"
    RECRUITER = "recruiter"
    INTERVIEW = "interview"
    OFFER = "offer"
    UNKNOWN = "unknown"


class MessageFixture(CorrespondenceModel):
    """Normalized message supplied by a provider adapter or deterministic fixture."""

    provider_message_id: NonEmpty
    thread_id: NonEmpty | None = None
    sender: NonEmpty
    recipients: tuple[NonEmpty, ...]
    subject: NonEmpty
    body_text: NonEmpty
    received_at: datetime

    @field_validator("received_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")
        return value


class ApplicationReference(CorrespondenceModel):
    candidate_id: NonEmpty
    application_id: UUID
    company: NonEmpty
    company_domain: NonEmpty
    job_title: NonEmpty
    external_references: tuple[NonEmpty, ...] = ()


class CorrespondenceRecord(CorrespondenceModel):
    provider_message_id: str
    message_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    kind: CorrespondenceKind
    candidate_id: str
    application_id: UUID | None
    association_reason: str
    received_at: datetime
    subject: str


class SubmittedAnswer(CorrespondenceModel):
    question: NonEmpty
    answer: NonEmpty


class ArchivedApplicationArtifacts(CorrespondenceModel):
    """Immutable, caller-supplied view of an application's archived evidence."""

    candidate_id: NonEmpty
    application_id: UUID
    company: NonEmpty
    job_title: NonEmpty
    exact_cv: NonEmpty
    exact_cover_letter: str | None = None
    submitted_answers: tuple[SubmittedAnswer, ...]
    original_job_description: NonEmpty
    job_score: Annotated[int, Field(ge=0, le=100)]
    score_rationale: NonEmpty
    candidate_job_match_summary: NonEmpty
    company_notes: tuple[NonEmpty, ...] = ()
    required_skills: tuple[NonEmpty, ...] = ()
    relevant_projects: tuple[NonEmpty, ...] = ()
    unsupported_areas: tuple[NonEmpty, ...] = ()
    salary_answer_submitted: str | None = None
    recruiter_correspondence: tuple[NonEmpty, ...] = ()


class InterviewPreparationPackage(CorrespondenceModel):
    candidate_id: str
    application_id: UUID
    company: str
    job_title: str
    exact_cv: str
    exact_cover_letter: str | None
    submitted_answers: tuple[SubmittedAnswer, ...]
    original_job_description: str
    job_score: int
    score_rationale: str
    candidate_job_match_summary: str
    company_notes: tuple[str, ...]
    likely_technical_questions: tuple[str, ...]
    likely_behavioral_questions: tuple[str, ...]
    relevant_projects: tuple[str, ...]
    unsupported_areas: tuple[str, ...]
    salary_answer_submitted: str | None
    recruiter_correspondence: tuple[str, ...]
    source_artifacts_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
