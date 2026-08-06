from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class DiscoveryContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceTrustLevel(StrEnum):
    OFFICIAL_ATS = "official_ats"
    OFFICIAL_COMPANY = "official_company"
    VERIFIED_THIRD_PARTY = "verified_third_party"


class LanguageRequirement(DiscoveryContract):
    language: str = Field(min_length=1, max_length=100)
    minimum_level: str | None = Field(default=None, pattern=r"^(A1|A2|B1|B2|C1|C2|native)$")


class NormalizedJob(DiscoveryContract):
    source: str = Field(min_length=1, max_length=100)
    external_job_id: str = Field(min_length=1, max_length=255)
    requisition_id: str | None = Field(default=None, max_length=255)
    company: str = Field(min_length=1, max_length=255)
    company_domain: str = Field(min_length=1, max_length=255)
    company_stage: str | None = Field(default=None, max_length=100)
    team: str | None = Field(default=None, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    normalized_title: str = Field(min_length=1, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    normalized_location: str | None = Field(default=None, max_length=255)
    remote_policy: str | None = Field(default=None, max_length=50)
    employment_type: str | None = Field(default=None, max_length=50)
    seniority: str | None = Field(default=None, max_length=50)
    description_raw: str = Field(min_length=1, max_length=500_000)
    description_normalized: str = Field(min_length=1, max_length=200_000)
    required_skills: tuple[str, ...] = Field(default=(), max_length=100)
    preferred_skills: tuple[str, ...] = Field(default=(), max_length=100)
    required_languages: tuple[LanguageRequirement, ...] = Field(default=(), max_length=32)
    required_experience_years_min: int | None = Field(default=None, ge=0, le=80)
    required_experience_years_max: int | None = Field(default=None, ge=0, le=80)
    salary_min: Decimal | None = Field(default=None, ge=0)
    salary_max: Decimal | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    salary_period: str | None = Field(default=None, max_length=50)
    salary_source: str | None = Field(default=None, max_length=255)
    visa_requirements: str | None = Field(default=None, max_length=2000)
    work_authorization_requirements: str | None = Field(default=None, max_length=2000)
    posted_at: datetime | None = None
    deadline: datetime | None = None
    expected_start_date: date | None = None
    source_url: HttpUrl
    application_url: HttpUrl
    ats_platform: str = Field(min_length=1)
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_trust_level: SourceTrustLevel = SourceTrustLevel.OFFICIAL_ATS
    raw_payload: dict[str, Any]

    @field_validator("company_domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        return value.strip().casefold().rstrip(".")

    @field_validator("required_skills", "preferred_skills")
    @classmethod
    def normalize_string_lists(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(value.strip() for value in values if value.strip()))
        if any(len(value) > 128 for value in normalized):
            raise ValueError("normalized job list values must not exceed 128 characters")
        return normalized

    @model_validator(mode="after")
    def ranges_are_ordered(self) -> NormalizedJob:
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_max < self.salary_min
        ):
            raise ValueError("salary maximum must be at least salary minimum")
        if (
            self.required_experience_years_min is not None
            and self.required_experience_years_max is not None
            and self.required_experience_years_max < self.required_experience_years_min
        ):
            raise ValueError("experience maximum must be at least experience minimum")
        return self


class JobPayloadAdapter(Protocol):
    platform: str

    def parse(
        self,
        payload: dict[str, Any],
        *,
        company: str,
        company_domain: str,
        discovered_at: datetime | None = None,
    ) -> NormalizedJob: ...
