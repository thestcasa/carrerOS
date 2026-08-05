from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

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
    description: str = Field(min_length=1)
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


def _classify(job: NormalizedJob, config: CandidateConfig) -> RoleClassification:
    targets = (*config.career_strategy.target_roles, *config.roles.target)
    if _matches(job.title, targets):
        return RoleClassification.TARGET
    title_tokens = _tokens(job.title) - _GENERIC_ROLE_TOKENS
    if any(title_tokens & (_tokens(role) - _GENERIC_ROLE_TOKENS) for role in targets):
        return RoleClassification.ADJACENT
    return RoleClassification.NON_TARGET


def _percentage(matched: int, total: int, *, empty: int) -> int:
    return empty if total == 0 else round(100 * matched / total)


def _dimension_values(
    job: NormalizedJob, config: CandidateConfig, classification: RoleClassification
) -> dict[str, tuple[int, tuple[str, ...], str]]:
    candidate_skills = {
        _normalized(skill) for category in config.skills.categories.values() for skill in category
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
        job.location, config.preferences.locations
    )
    mode_match = job.work_mode is not None and job.work_mode in config.preferences.work_modes
    location_score = 100 if location_match or mode_match else 0
    domain_match = job.domain is not None and _matches(
        job.domain, config.career_strategy.priority_domains
    )
    company_match = _matches(job.company, config.companies.target)
    compensation_score = 50
    salary_evidence: tuple[str, ...] = ("salary:unknown",)
    if job.salary_currency == config.preferences.salary.currency and job.salary_max is not None:
        compensation_score = 100 if job.salary_max >= config.preferences.salary.minimum else 0
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


def _hard_blockers(job: NormalizedJob, config: CandidateConfig) -> tuple[str, ...]:
    blockers: list[str] = []
    if _matches(job.company, config.companies.blocked):
        blockers.append("company_blocked")
    if _matches(job.title, config.roles.blocked):
        blockers.append("role_blocked")
    if job.domain is not None and _matches(job.domain, config.career_strategy.excluded_domains):
        blockers.append("domain_excluded")
    if (
        job.employment_type is not None
        and job.employment_type not in config.preferences.employment_types
    ):
        blockers.append("employment_type_incompatible")
    location_matches = job.location is not None and _matches(
        job.location, config.preferences.locations
    )
    mode_matches = job.work_mode is not None and job.work_mode in config.preferences.work_modes
    if (job.location is not None or job.work_mode is not None) and not (
        location_matches or mode_matches or config.preferences.willing_to_relocate
    ):
        blockers.append("location_incompatible")
    if (
        job.salary_currency == config.preferences.salary.currency
        and job.salary_max is not None
        and job.salary_max < config.preferences.salary.minimum
    ):
        blockers.append("salary_below_minimum")
    candidate_languages = {
        item.language.casefold(): _LEVEL_RANK[item.level] for item in config.languages.items
    }
    for requirement in job.required_languages:
        if (
            candidate_languages.get(requirement.language.casefold(), 0)
            < _LEVEL_RANK[requirement.minimum_level]
        ):
            blockers.append(f"language_incompatible:{requirement.language.casefold()}")
    return tuple(blockers)


def evaluate_job(job: NormalizedJob, config: CandidateConfig) -> JobEvaluation:
    classification = _classify(job, config)
    values = _dimension_values(job, config, classification)
    dimensions: list[DimensionScore] = []
    total = Decimal(0)
    for name, weight in config.scoring_rules.weights.items():
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
    blockers = _hard_blockers(job, config)
    if blockers:
        action = "skip"
    elif total_score >= config.scoring_rules.application_threshold:
        action = "prepare"
    elif total_score >= config.scoring_rules.human_review_threshold:
        action = "review"
    else:
        action = "skip"
    evidence = tuple(item for dimension in dimensions for item in dimension.evidence)
    return JobEvaluation(
        candidate_id=config.manifest.candidate_id,
        job_id=job.job_id,
        classification=classification,
        total_score=total_score,
        proposed_action=action,
        hard_blockers=blockers,
        dimensions=tuple(dimensions),
        evidence=evidence,
    )
