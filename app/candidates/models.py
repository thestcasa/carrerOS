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
HttpsUrl = Annotated[str, StringConstraints(pattern=r"^https://[^\s]+$", strip_whitespace=True)]
PhoneNumber = Annotated[
    str,
    StringConstraints(pattern=r"^\+?[0-9][0-9(). -]{5,30}$", strip_whitespace=True),
]


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
    certifications: str | None = None
    publications: str | None = None
    notification_rules: str | None = None


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
    phone: PhoneNumber
    city: NonEmptyStr
    country_code: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
    preferred_name: str | None = None
    pronouns: str | None = None
    region: str | None = None
    country: str | None = None
    linkedin: HttpsUrl | None = None
    personal_website: HttpsUrl | None = None
    github: HttpsUrl | None = None
    portfolio: HttpsUrl | None = None
    other_links: tuple[HttpsUrl, ...] = ()
    approved: bool = False


class Biography(StrictModel):
    summary: NonEmptyStr
    highlights: tuple[NonEmptyStr, ...]
    headline: str | None = None
    long_bio: str | None = None
    career_stage: (
        Literal["student", "graduate", "early_career", "mid_level", "senior", "executive"] | None
    ) = None
    primary_professional_identity: str | None = None
    approved: bool = False


class DateRangeModel(StrictModel):
    start_date: date
    end_date: date | None = None

    @model_validator(mode="after")
    def dates_are_ordered(self) -> DateRangeModel:
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class ClaimFact(StrictModel):
    id: StableId
    statement: NonEmptyStr
    verified: bool = False
    source: str | None = None
    publicly_usable: bool = False
    confidentiality: Literal["public", "restricted", "internal"] = "restricted"
    approved: bool = False
    archived: bool = False


class EducationItem(DateRangeModel):
    id: StableId
    institution: NonEmptyStr
    qualification: NonEmptyStr
    field_of_study: NonEmptyStr
    location: NonEmptyStr
    completed: bool | None = None
    grade: str | None = None
    coursework: tuple[str, ...] = ()
    cv_eligible: bool = True
    approved: bool = False
    archived: bool = False


class Education(StrictModel):
    items: tuple[EducationItem, ...]

    @model_validator(mode="after")
    def education_ids_are_unique(self) -> Education:
        item_ids = [item.id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("duplicate education IDs are not allowed")
        return self


class ExperienceItem(DateRangeModel):
    id: StableId
    organization: NonEmptyStr
    title: NonEmptyStr
    location: NonEmptyStr
    achievements: tuple[ClaimFact | NonEmptyStr, ...]
    skills: tuple[NonEmptyStr, ...]
    employment_type: (
        Literal["full_time", "part_time", "internship", "freelance", "contract"] | None
    ) = None
    remote_policy: Literal["remote", "hybrid", "onsite", "unknown"] = "unknown"
    current: bool = False
    summary: str | None = None
    responsibilities: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    role_categories: tuple[str, ...] = ()
    confidentiality: Literal["public", "restricted", "internal"] = "restricted"
    cv_eligible: bool = True
    cover_letter_eligible: bool = True
    approved: bool = False
    archived: bool = False

    @model_validator(mode="after")
    def current_role_has_no_end_date(self) -> ExperienceItem:
        if self.current and self.end_date is not None:
            raise ValueError("current experience cannot have an end_date")
        if not self.current and self.end_date is None:
            raise ValueError("non-current experience requires an end_date")
        return self


class Experience(StrictModel):
    items: tuple[ExperienceItem, ...]

    @model_validator(mode="after")
    def experience_ids_are_unique(self) -> Experience:
        item_ids = [item.id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("duplicate experience IDs are not allowed")
        return self


class ProjectItem(DateRangeModel):
    id: StableId
    name: NonEmptyStr
    description: NonEmptyStr
    outcomes: tuple[ClaimFact | NonEmptyStr, ...]
    skills: tuple[NonEmptyStr, ...]
    url: HttpsUrl | None = None
    project_type: (
        Literal["professional", "academic", "personal", "open_source", "research"] | None
    ) = None
    status: Literal["planned", "active", "completed", "paused"] = "completed"
    domains: tuple[str, ...] = ()
    role_categories: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    confidentiality: Literal["public", "restricted", "internal"] = "restricted"
    public_summary: str | None = None
    cv_eligible: bool = True
    cover_letter_eligible: bool = True
    interview_eligible: bool = True
    approved: bool = False
    archived: bool = False


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
    approved: bool = False


class LanguageItem(StrictModel):
    language: NonEmptyStr
    level: Literal["A1", "A2", "B1", "B2", "C1", "C2", "native"]
    professional_use: bool = False
    approved: bool = False
    archived: bool = False


class Languages(StrictModel):
    items: tuple[LanguageItem, ...]


class RoleTier(StrictModel):
    tier: Annotated[int, Field(ge=1)]
    name: NonEmptyStr
    roles: tuple[NonEmptyStr, ...]
    application_share_target: Annotated[Decimal, Field(ge=0, le=1)]


class CareerStrategy(StrictModel):
    target_roles: tuple[NonEmptyStr, ...]
    priority_domains: tuple[NonEmptyStr, ...]
    excluded_domains: tuple[NonEmptyStr, ...] = ()
    objectives: tuple[NonEmptyStr, ...]
    role_tiers: tuple[RoleTier, ...] = ()
    preferred_company_stages: tuple[str, ...] = ()
    preferred_company_types: tuple[str, ...] = ()
    approved: bool = False

    @model_validator(mode="after")
    def application_shares_are_valid(self) -> CareerStrategy:
        application_share = sum(
            (tier.application_share_target for tier in self.role_tiers), Decimal(0)
        )
        if application_share > Decimal(1):
            raise ValueError("role tier application shares cannot exceed 1")
        return self


class ScoringRules(StrictModel):
    application_threshold: Annotated[int, Field(ge=0, le=100)]
    human_review_threshold: Annotated[int, Field(ge=0, le=100)]
    weights: dict[NonEmptyStr, Annotated[Decimal, Field(ge=0, le=1)]]
    bonuses: tuple[str, ...] = ()
    penalties: tuple[str, ...] = ()
    approved: bool = False

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
    relocation_destinations: tuple[str, ...] = ()
    full_time_start: date | None = None
    part_time_available: bool = False
    notice_period_days: Annotated[int, Field(ge=0)] | None = None
    maximum_applications_per_company_30_days: Annotated[int, Field(ge=1, le=100)] = 3
    maximum_applications_per_day: Annotated[int, Field(ge=1, le=100)] = 5
    approved: bool = False


class LegalStatus(StrictModel):
    jurisdictions: tuple[NonEmptyStr, ...]
    work_authorization_confirmed: bool
    requires_sponsorship: bool
    approved_for_automated_use: bool
    citizenships: tuple[str, ...] = ()
    may_require_sponsorship_in_future: bool | None = None
    permit_type: str | None = None
    permit_expiration: date | None = None
    approved: bool = False
    last_verified: date | None = None


class ApprovedAnswer(StrictModel):
    key: StableId
    question_pattern: NonEmptyStr
    answer: NonEmptyStr
    evidence_ids: tuple[StableId, ...] = ()
    question_categories: tuple[str, ...] = ()
    approved: bool = False
    sensitive: bool = False
    auto_submit_allowed: bool = False
    valid_from: date | None = None
    valid_until: date | None = None
    archived: bool = False

    @model_validator(mode="after")
    def validity_dates_are_ordered(self) -> ApprovedAnswer:
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until < self.valid_from
        ):
            raise ValueError("valid_until must not be before valid_from")
        return self


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
    template_id: Literal["technical_single_page", "technical_two_page"] = "technical_two_page"
    template_version: Literal["1.0"] = "1.0"
    allowed_sections: tuple[NonEmptyStr, ...]
    forbidden_claims: tuple[NonEmptyStr, ...]
    require_evidence_ids: bool
    approved: bool = False


class CoverLetterRules(StrictModel):
    enabled: bool
    max_words: Annotated[int, Field(ge=50, le=2000)]
    tone: NonEmptyStr
    forbidden_claims: tuple[NonEmptyStr, ...]
    require_evidence_ids: bool
    approved: bool = False


class CompanyRules(StrictModel):
    target: tuple[NonEmptyStr, ...]
    blocked: tuple[NonEmptyStr, ...]
    approved: bool = False

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
    approved: bool = False

    @model_validator(mode="after")
    def lists_do_not_overlap(self) -> RoleRules:
        if {value.casefold() for value in self.target} & {
            value.casefold() for value in self.blocked
        }:
            raise ValueError("target and blocked roles must not overlap")
        return self


class CertificationItem(StrictModel):
    id: StableId
    name: NonEmptyStr
    issuer: NonEmptyStr
    issued_date: date | None = None
    expiration_date: date | None = None
    credential_url: HttpsUrl | None = None
    cv_eligible: bool = True
    approved: bool = False
    archived: bool = False

    @model_validator(mode="after")
    def expiration_follows_issue(self) -> CertificationItem:
        if (
            self.issued_date is not None
            and self.expiration_date is not None
            and self.expiration_date < self.issued_date
        ):
            raise ValueError("expiration_date must not be before issued_date")
        return self


class Certifications(StrictModel):
    items: tuple[CertificationItem, ...] = ()

    @model_validator(mode="after")
    def certification_ids_are_unique(self) -> Certifications:
        item_ids = [item.id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("duplicate certification IDs are not allowed")
        return self


class PublicationItem(StrictModel):
    id: StableId
    title: NonEmptyStr
    publisher: str | None = None
    published_date: date | None = None
    url: HttpsUrl | None = None
    summary: str | None = None
    cv_eligible: bool = True
    approved: bool = False
    archived: bool = False


class Publications(StrictModel):
    items: tuple[PublicationItem, ...] = ()

    @model_validator(mode="after")
    def publication_ids_are_unique(self) -> Publications:
        item_ids = [item.id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("duplicate publication IDs are not allowed")
        return self


class NotificationRules(StrictModel):
    immediate_events: tuple[NonEmptyStr, ...] = ()
    digest_enabled: bool = True
    digest_frequency: Literal["daily", "weekly"] = "daily"
    channels: tuple[Literal["web", "email"], ...] = ("web",)
    approved: bool = False


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
    certifications: Certifications = Field(default_factory=Certifications)
    publications: Publications = Field(default_factory=Publications)
    notification_rules: NotificationRules = Field(default_factory=NotificationRules)

    @model_validator(mode="after")
    def candidate_ids_match(self) -> CandidateConfig:
        if self.manifest.candidate_id != self.identity.candidate_id:
            raise ValueError("manifest and identity candidate_id values must match")
        return self
