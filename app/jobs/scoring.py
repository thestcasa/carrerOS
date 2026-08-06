from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.candidates.models import CandidateConfig


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RoleClassification(StrEnum):
    TARGET = "target"
    ADJACENT = "adjacent"
    NON_TARGET = "non_target"


class RequiredLanguage(_FrozenModel):
    language: str = Field(min_length=1)
    minimum_level: str = Field(pattern=r"^(A1|A2|B1|B2|C1|C2|native)$")


class NormalizedJob(_FrozenModel):
    job_id: str = Field(min_length=1)
    company: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1, max_length=200_000)
    location: str | None = None
    work_mode: str | None = None
    employment_type: str | None = None
    domain: str | None = None
    required_skills: tuple[str, ...] = ()
    preferred_skills: tuple[str, ...] = ()
    required_languages: tuple[RequiredLanguage, ...] = ()
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class CareerScoringPolicy(_FrozenModel):
    target_roles: tuple[str, ...]
    priority_domains: tuple[str, ...]
    excluded_domains: tuple[str, ...]


class RoleScoringPolicy(_FrozenModel):
    target: tuple[str, ...]
    blocked: tuple[str, ...]


class SkillScoringPolicy(_FrozenModel):
    categories: dict[str, tuple[str, ...]]


class ScorePolicy(_FrozenModel):
    application_threshold: int = Field(ge=0, le=100)
    human_review_threshold: int = Field(ge=0, le=100)
    weights: dict[str, Decimal]

    @model_validator(mode="after")
    def thresholds_and_weights_are_valid(self) -> ScorePolicy:
        if self.human_review_threshold > self.application_threshold:
            raise ValueError("human review threshold cannot exceed application threshold")
        if any(weight < 0 or weight > 1 for weight in self.weights.values()):
            raise ValueError("scoring weights must be between zero and one")
        if sum(self.weights.values(), Decimal(0)) != Decimal(1):
            raise ValueError("scoring weights must sum to one")
        return self


class SalaryScoringPolicy(_FrozenModel):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    minimum: int = Field(ge=0)


class PreferenceScoringPolicy(_FrozenModel):
    locations: tuple[str, ...]
    work_modes: tuple[str, ...]
    employment_types: tuple[str, ...]
    salary: SalaryScoringPolicy
    willing_to_relocate: bool


class CompanyScoringPolicy(_FrozenModel):
    target: tuple[str, ...]
    blocked: tuple[str, ...]


class LanguageScoringPolicy(_FrozenModel):
    language: str = Field(min_length=1)
    level: str = Field(pattern=r"^(A1|A2|B1|B2|C1|C2|native)$")


class CandidateScoringContext(_FrozenModel):
    """Least-privilege candidate policy exposed to the analysis-agent boundary."""

    candidate_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    profile_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    career_strategy: CareerScoringPolicy
    roles: RoleScoringPolicy
    skills: SkillScoringPolicy
    scoring_rules: ScorePolicy
    preferences: PreferenceScoringPolicy
    companies: CompanyScoringPolicy
    languages: tuple[LanguageScoringPolicy, ...]

    @classmethod
    def from_config(cls, config: CandidateConfig) -> CandidateScoringContext:
        return cls(
            candidate_id=config.manifest.candidate_id,
            profile_version=config.manifest.profile_version,
            career_strategy=CareerScoringPolicy(
                target_roles=config.career_strategy.target_roles,
                priority_domains=config.career_strategy.priority_domains,
                excluded_domains=config.career_strategy.excluded_domains,
            ),
            roles=RoleScoringPolicy(target=config.roles.target, blocked=config.roles.blocked),
            skills=SkillScoringPolicy(categories=config.skills.categories),
            scoring_rules=ScorePolicy(
                application_threshold=config.scoring_rules.application_threshold,
                human_review_threshold=config.scoring_rules.human_review_threshold,
                weights=dict(sorted(config.scoring_rules.weights.items())),
            ),
            preferences=PreferenceScoringPolicy(
                locations=config.preferences.locations,
                work_modes=config.preferences.work_modes,
                employment_types=config.preferences.employment_types,
                salary=SalaryScoringPolicy(
                    currency=config.preferences.salary.currency,
                    minimum=config.preferences.salary.minimum,
                ),
                willing_to_relocate=config.preferences.willing_to_relocate,
            ),
            companies=CompanyScoringPolicy(
                target=config.companies.target,
                blocked=config.companies.blocked,
            ),
            languages=tuple(
                LanguageScoringPolicy(language=item.language, level=item.level)
                for item in config.languages.items
                if item.approved and not item.archived
            ),
        )


class DimensionScore(_FrozenModel):
    name: str
    score: int = Field(ge=0, le=100)
    weight: Decimal = Field(ge=0, le=1)
    contribution: Decimal = Field(ge=0, le=100)
    evidence: tuple[str, ...]
    explanation: str


class JobEvaluation(_FrozenModel):
    candidate_id: str
    job_id: str
    classification: RoleClassification
    total_score: int = Field(ge=0, le=100)
    proposed_action: str
    hard_blockers: tuple[str, ...]
    dimensions: tuple[DimensionScore, ...]
    evidence: tuple[str, ...]


_LEVEL_RANK = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6, "native": 7}
_WORD_RE = re.compile(r"[a-z0-9+#.]+")
_GENERIC_ROLE_TOKENS = frozenset({"engineer", "developer", "specialist", "manager", "lead"})


def _normalized(value: str) -> str:
    return " ".join(_WORD_RE.findall(value.casefold()))


def _tokens(value: str) -> frozenset[str]:
    return frozenset(_WORD_RE.findall(value.casefold()))


def _matches(value: str, configured: tuple[str, ...]) -> bool:
    normalized = _normalized(value)
    return any(normalized == _normalized(item) for item in configured)


def _classify(job: NormalizedJob, context: CandidateScoringContext) -> RoleClassification:
    targets = (*context.career_strategy.target_roles, *context.roles.target)
    if _matches(job.title, targets):
        return RoleClassification.TARGET
    title_tokens = _tokens(job.title) - _GENERIC_ROLE_TOKENS
    if any(title_tokens & (_tokens(role) - _GENERIC_ROLE_TOKENS) for role in targets):
        return RoleClassification.ADJACENT
    return RoleClassification.NON_TARGET


def _percentage(matched: int, total: int, *, empty: int) -> int:
    return empty if total == 0 else round(100 * matched / total)


def _dimension_values(
    job: NormalizedJob, context: CandidateScoringContext, classification: RoleClassification
) -> dict[str, tuple[int, tuple[str, ...], str]]:
    candidate_skills = {
        _normalized(skill) for category in context.skills.categories.values() for skill in category
    }
    required = {_normalized(skill) for skill in job.required_skills}
    preferred = {_normalized(skill) for skill in job.preferred_skills}
    skill_matches = tuple(sorted(candidate_skills & (required | preferred)))
    skill_score = _percentage(
        len(candidate_skills & required) * 2 + len(candidate_skills & preferred),
        len(required) * 2 + len(preferred),
        empty=50,
    )
    location_match = job.location is not None and _matches(
        job.location, context.preferences.locations
    )
    mode_match = job.work_mode is not None and job.work_mode in context.preferences.work_modes
    location_score = 100 if location_match or mode_match else 0
    domain_match = job.domain is not None and _matches(
        job.domain, context.career_strategy.priority_domains
    )
    company_match = _matches(job.company, context.companies.target)
    compensation_score = 50
    salary_evidence: tuple[str, ...] = ("salary:unknown",)
    if job.salary_currency == context.preferences.salary.currency and job.salary_max is not None:
        compensation_score = 100 if job.salary_max >= context.preferences.salary.minimum else 0
        salary_evidence = (f"salary_max:{job.salary_max}:{job.salary_currency}",)
    role_score = {
        RoleClassification.TARGET: 100,
        RoleClassification.ADJACENT: 60,
        RoleClassification.NON_TARGET: 0,
    }[classification]
    values = {
        "role_alignment": (
            role_score,
            (f"classification:{classification.value}",),
            "Role title alignment.",
        ),
        "skills_alignment": (
            skill_score,
            tuple(f"skill:{item}" for item in skill_matches),
            "Required and preferred skill coverage.",
        ),
        "location_alignment": (
            location_score,
            (f"location:{job.location or 'unknown'}", f"work_mode:{job.work_mode or 'unknown'}"),
            "Configured location or work-mode compatibility.",
        ),
        "domain_alignment": (
            100 if domain_match else 0,
            (f"domain:{job.domain or 'unknown'}",),
            "Candidate priority-domain alignment.",
        ),
        "compensation_alignment": (
            compensation_score,
            salary_evidence,
            "Candidate minimum compensation compatibility.",
        ),
        "company_alignment": (
            100 if company_match else 50,
            (f"company:{job.company}",),
            "Candidate company preference alignment.",
        ),
    }
    return values


def _hard_blockers(job: NormalizedJob, context: CandidateScoringContext) -> tuple[str, ...]:
    blockers: list[str] = []
    if _matches(job.company, context.companies.blocked):
        blockers.append("company_blocked")
    if _matches(job.title, context.roles.blocked):
        blockers.append("role_blocked")
    if job.domain is not None and _matches(job.domain, context.career_strategy.excluded_domains):
        blockers.append("domain_excluded")
    if (
        job.employment_type is not None
        and job.employment_type not in context.preferences.employment_types
    ):
        blockers.append("employment_type_incompatible")
    location_matches = job.location is not None and _matches(
        job.location, context.preferences.locations
    )
    mode_matches = job.work_mode is not None and job.work_mode in context.preferences.work_modes
    if (job.location is not None or job.work_mode is not None) and not (
        location_matches or mode_matches or context.preferences.willing_to_relocate
    ):
        blockers.append("location_incompatible")
    if (
        job.salary_currency == context.preferences.salary.currency
        and job.salary_max is not None
        and job.salary_max < context.preferences.salary.minimum
    ):
        blockers.append("salary_below_minimum")
    candidate_languages = {
        item.language.casefold(): _LEVEL_RANK[item.level] for item in context.languages
    }
    for requirement in job.required_languages:
        if (
            candidate_languages.get(requirement.language.casefold(), 0)
            < _LEVEL_RANK[requirement.minimum_level]
        ):
            blockers.append(f"language_incompatible:{requirement.language.casefold()}")
    return tuple(blockers)


def evaluate_job(job: NormalizedJob, config: CandidateConfig) -> JobEvaluation:
    return evaluate_job_with_context(job, CandidateScoringContext.from_config(config))


def evaluate_job_with_context(
    job: NormalizedJob, context: CandidateScoringContext
) -> JobEvaluation:
    classification = _classify(job, context)
    values = _dimension_values(job, context, classification)
    dimensions: list[DimensionScore] = []
    total = Decimal(0)
    for name, weight in context.scoring_rules.weights.items():
        score, evidence, explanation = values.get(
            name, (0, (f"unsupported_dimension:{name}",), "No deterministic scorer is configured.")
        )
        contribution = (Decimal(score) * weight).quantize(Decimal("0.01"))
        total += contribution
        dimensions.append(
            DimensionScore(
                name=name,
                score=score,
                weight=weight,
                contribution=contribution,
                evidence=evidence,
                explanation=explanation,
            )
        )
    total_score = int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    blockers = _hard_blockers(job, context)
    if blockers:
        action = "skip"
    elif total_score >= context.scoring_rules.application_threshold:
        action = "prepare"
    elif total_score >= context.scoring_rules.human_review_threshold:
        action = "review"
    else:
        action = "skip"
    evidence = tuple(item for dimension in dimensions for item in dimension.evidence)
    return JobEvaluation(
        candidate_id=context.candidate_id,
        job_id=job.job_id,
        classification=classification,
        total_score=total_score,
        proposed_action=action,
        hard_blockers=blockers,
        dimensions=tuple(dimensions),
        evidence=evidence,
    )
