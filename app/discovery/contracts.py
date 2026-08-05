from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class DiscoveryContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceTrustLevel(StrEnum):
    OFFICIAL_ATS = "official_ats"
    OFFICIAL_COMPANY = "official_company"
    VERIFIED_THIRD_PARTY = "verified_third_party"


class NormalizedJob(DiscoveryContract):
    source: str = Field(min_length=1)
    external_job_id: str = Field(min_length=1)
    requisition_id: str | None = None
    company: str = Field(min_length=1)
    company_domain: str = Field(min_length=1)
    title: str = Field(min_length=1)
    normalized_title: str = Field(min_length=1)
    location: str | None = None
    remote_policy: str | None = None
    employment_type: str | None = None
    description_raw: str = Field(min_length=1)
    description_normalized: str = Field(min_length=1)
    salary_min: Decimal | None = Field(default=None, ge=0)
    salary_max: Decimal | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    posted_at: datetime | None = None
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
