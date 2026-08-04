from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

CandidateId = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]{2,63}$", strip_whitespace=True),
]
StableId = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_-]{1,63}$", strip_whitespace=True),
]
NonEmptyStr = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ManifestFiles(StrictModel):
    identity: str
    biography: str
    education: str
    experience: str
    projects: str
    skills: str
    languages: str
    career_strategy: str
    scoring_rules: str
    preferences: str
    legal_status: str
    approved_answers: str
    cv_rules: str
    cover_letter_rules: str
    companies: str
    roles: str


class CandidateWorkflow(StrictModel):
    discovery_enabled: bool
    automatic_submission_enabled: bool
    email_tracking_enabled: bool
    notifications_enabled: bool


class CandidateApprovals(StrictModel):
    profile_approved: bool
    legal_status_approved: bool
    automatic_answers_approved: bool
    cv_templates_approved: bool


class ProfileManifest(StrictModel):
    schema_version: Literal["1.0"]
    candidate_id: CandidateId
    profile_version: Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    display_name: NonEmptyStr
    active: bool
    data_files: ManifestFiles
    workflow: CandidateWorkflow
    validation: CandidateApprovals


class Identity(StrictModel):
    candidate_id: CandidateId
    full_name: NonEmptyStr
    email: Annotated[str, StringConstraints(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
    phone: NonEmptyStr
    city: NonEmptyStr
    country_code: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]


class Biography(StrictModel):
    summary: NonEmptyStr
    highlights: tuple[NonEmptyStr, ...]


class DateRangeModel(StrictModel):
    start_date: date
    end_date: date | None = None

    @model_validator(mode="after")
    def dates_are_ordered(self) -> DateRangeModel:
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class EducationItem(DateRangeModel):
    id: StableId
    institution: NonEmptyStr
    qualification: NonEmptyStr
    field_of_study: NonEmptyStr
    location: NonEmptyStr


class Education(StrictModel):
    items: tuple[EducationItem, ...]


class ExperienceItem(DateRangeModel):
    id: StableId
    organization: NonEmptyStr
    title: NonEmptyStr
    location: NonEmptyStr
    achievements: tuple[NonEmptyStr, ...]
    skills: tuple[NonEmptyStr, ...]


class Experience(StrictModel):
    items: tuple[ExperienceItem, ...]


class ProjectItem(DateRangeModel):
    id: StableId
    name: NonEmptyStr
    description: NonEmptyStr
    outcomes: tuple[NonEmptyStr, ...]
    skills: tuple[NonEmptyStr, ...]
    url: str | None = None


class Projects(StrictModel):
    items: tuple[ProjectItem, ...]

    @model_validator(mode="after")
    def project_ids_are_unique(self) -> Projects:
        project_ids = [item.id for item in self.items]
        if len(project_ids) != len(set(project_ids)):
            raise ValueError("duplicate project IDs are not allowed")
        return self


class Skills(StrictModel):
    categories: dict[NonEmptyStr, tuple[NonEmptyStr, ...]]


class LanguageItem(StrictModel):
    language: NonEmptyStr
    level: Literal["A1", "A2", "B1", "B2", "C1", "C2", "native"]


class Languages(StrictModel):
    items: tuple[LanguageItem, ...]


class CareerStrategy(StrictModel):
    target_roles: tuple[NonEmptyStr, ...]
    priority_domains: tuple[NonEmptyStr, ...]
    excluded_domains: tuple[NonEmptyStr, ...] = ()
    objectives: tuple[NonEmptyStr, ...]


class ScoringRules(StrictModel):
    application_threshold: Annotated[int, Field(ge=0, le=100)]
    human_review_threshold: Annotated[int, Field(ge=0, le=100)]
    weights: dict[NonEmptyStr, Annotated[Decimal, Field(ge=0, le=1)]]

    @model_validator(mode="after")
    def validate_scoring(self) -> ScoringRules:
        if self.human_review_threshold > self.application_threshold:
            raise ValueError("human_review_threshold cannot exceed application_threshold")
        if sum(self.weights.values(), start=Decimal(0)) != Decimal(1):
            raise ValueError("scoring weights must sum exactly to 1")
        return self


class SalaryPreference(StrictModel):
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
    minimum: Annotated[int, Field(ge=0)]
    maximum: Annotated[int, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def maximum_is_valid(self) -> SalaryPreference:
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("salary maximum must be at least the minimum")
        return self


class Preferences(StrictModel):
    locations: tuple[NonEmptyStr, ...]
    work_modes: tuple[Literal["remote", "hybrid", "onsite"], ...]
    employment_types: tuple[Literal["permanent", "contract", "internship"], ...]
    salary: SalaryPreference
    willing_to_relocate: bool


class LegalStatus(StrictModel):
    jurisdictions: tuple[NonEmptyStr, ...]
    work_authorization_confirmed: bool
    requires_sponsorship: bool
    approved_for_automated_use: bool


class ApprovedAnswer(StrictModel):
    key: StableId
    question_pattern: NonEmptyStr
    answer: NonEmptyStr
    evidence_ids: tuple[StableId, ...] = ()


class ApprovedAnswers(StrictModel):
    items: tuple[ApprovedAnswer, ...]

    @model_validator(mode="after")
    def answer_keys_are_unique(self) -> ApprovedAnswers:
        keys = [item.key for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate approved-answer keys are not allowed")
        return self


class CVRules(StrictModel):
    max_pages: Annotated[int, Field(ge=1, le=5)]
    allowed_sections: tuple[NonEmptyStr, ...]
    forbidden_claims: tuple[NonEmptyStr, ...]
    require_evidence_ids: bool


class CoverLetterRules(StrictModel):
    enabled: bool
    max_words: Annotated[int, Field(ge=50, le=2000)]
    tone: NonEmptyStr
    forbidden_claims: tuple[NonEmptyStr, ...]
    require_evidence_ids: bool


class CompanyRules(StrictModel):
    target: tuple[NonEmptyStr, ...]
    blocked: tuple[NonEmptyStr, ...]

    @model_validator(mode="after")
    def lists_do_not_overlap(self) -> CompanyRules:
        if {value.casefold() for value in self.target} & {
            value.casefold() for value in self.blocked
        }:
            raise ValueError("target and blocked companies must not overlap")
        return self


class RoleRules(StrictModel):
    target: tuple[NonEmptyStr, ...]
    blocked: tuple[NonEmptyStr, ...]

    @model_validator(mode="after")
    def lists_do_not_overlap(self) -> RoleRules:
        if {value.casefold() for value in self.target} & {
            value.casefold() for value in self.blocked
        }:
            raise ValueError("target and blocked roles must not overlap")
        return self


class CandidateConfig(StrictModel):
    manifest: ProfileManifest
    identity: Identity
    biography: Biography
    education: Education
    experience: Experience
    projects: Projects
    skills: Skills
    languages: Languages
    career_strategy: CareerStrategy
    scoring_rules: ScoringRules
    preferences: Preferences
    legal_status: LegalStatus
    approved_answers: ApprovedAnswers
    cv_rules: CVRules
    cover_letter_rules: CoverLetterRules
    companies: CompanyRules
    roles: RoleRules

    @model_validator(mode="after")
    def candidate_ids_match(self) -> CandidateConfig:
        if self.manifest.candidate_id != self.identity.candidate_id:
            raise ValueError("manifest and identity candidate_id values must match")
        return self
