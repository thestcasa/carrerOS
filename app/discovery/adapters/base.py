from __future__ import annotations

import html
import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.discovery.contracts import LanguageRequirement, NormalizedJob
from app.discovery.security import validate_https_url


class AdapterPayloadError(ValueError):
    pass


def required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, (str, int)) or not str(value).strip():
        raise AdapterPayloadError(f"missing or invalid {key}")
    return str(value).strip()


def nested_string(payload: dict[str, Any], parent: str, child: str) -> str | None:
    container = payload.get(parent)
    if not isinstance(container, dict):
        return None
    value = container.get(child)
    return value.strip() if isinstance(value, str) and value.strip() else None


def optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise AdapterPayloadError(f"invalid {key}")
    return value.strip()


def string_tuple(payload: dict[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if value is None:
        return ()
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise AdapterPayloadError(f"invalid {key}")
    return tuple(item.strip() for item in value)


def language_requirements(payload: dict[str, Any]) -> tuple[LanguageRequirement, ...]:
    value = payload.get("required_languages")
    if value is None:
        return ()
    if not isinstance(value, list):
        raise AdapterPayloadError("invalid required_languages")
    requirements: list[LanguageRequirement] = []
    for item in value:
        if isinstance(item, str):
            requirements.append(LanguageRequirement(language=item))
        elif isinstance(item, dict):
            try:
                requirements.append(LanguageRequirement.model_validate(item))
            except ValueError as exc:
                raise AdapterPayloadError("invalid required_languages") from exc
        else:
            raise AdapterPayloadError("invalid required_languages")
    return tuple(requirements)


def optional_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdapterPayloadError(f"invalid {key}")
    return int(value)


def optional_decimal(payload: dict[str, Any], key: str) -> Decimal | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, str | int | float | Decimal):
        raise AdapterPayloadError(f"invalid {key}")
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise AdapterPayloadError(f"invalid {key}") from exc


def plain_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(without_tags).split())


def parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value) / 1000, tz=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AdapterPayloadError("invalid posted date") from exc
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    raise AdapterPayloadError("invalid posted date")


def parse_date(value: object) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AdapterPayloadError("invalid expected start date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AdapterPayloadError("invalid expected start date") from exc


def validated_url(value: str, allowed_domains: tuple[str, ...]) -> str:
    result = validate_https_url(value, allowed_domains)
    if not result.allowed or result.normalized_url is None:
        raise AdapterPayloadError(f"unsafe job URL: {result.reason}")
    return result.normalized_url


def build_job(
    *,
    platform: str,
    payload: dict[str, Any],
    external_id: str,
    title: str,
    description: str,
    location: str | None,
    source_url: str,
    application_url: str,
    allowed_domains: tuple[str, ...],
    company: str,
    company_domain: str,
    posted_at: datetime | None,
    discovered_at: datetime | None,
    requisition_id: str | None = None,
    remote_policy: str | None = None,
    employment_type: str | None = None,
    seniority: str | None = None,
    team: str | None = None,
) -> NormalizedJob:
    normalized_description = plain_text(description)
    if not normalized_description:
        raise AdapterPayloadError("empty normalized description")
    return NormalizedJob(
        source=platform,
        external_job_id=external_id,
        requisition_id=requisition_id,
        company=company,
        company_domain=company_domain,
        company_stage=optional_string(payload, "company_stage"),
        team=team or optional_string(payload, "team"),
        title=title,
        normalized_title=" ".join(title.casefold().split()),
        location=location,
        normalized_location=optional_string(payload, "normalized_location")
        or (" ".join(location.casefold().split()) if location else None),
        remote_policy=remote_policy or optional_string(payload, "remote_policy"),
        employment_type=employment_type or optional_string(payload, "employment_type"),
        seniority=seniority or optional_string(payload, "seniority"),
        description_raw=description,
        description_normalized=normalized_description,
        required_skills=string_tuple(payload, "required_skills"),
        preferred_skills=string_tuple(payload, "preferred_skills"),
        required_languages=language_requirements(payload),
        required_experience_years_min=optional_int(payload, "required_experience_years_min"),
        required_experience_years_max=optional_int(payload, "required_experience_years_max"),
        salary_min=optional_decimal(payload, "salary_min"),
        salary_max=optional_decimal(payload, "salary_max"),
        salary_currency=(optional_string(payload, "salary_currency") or "").upper() or None,
        salary_period=optional_string(payload, "salary_period"),
        salary_source=optional_string(payload, "salary_source"),
        visa_requirements=optional_string(payload, "visa_requirements"),
        work_authorization_requirements=optional_string(payload, "work_authorization_requirements"),
        posted_at=posted_at,
        deadline=parse_datetime(payload.get("deadline")),
        expected_start_date=parse_date(payload.get("expected_start_date")),
        source_url=validated_url(source_url, allowed_domains),
        application_url=validated_url(application_url, allowed_domains),
        ats_platform=platform,
        discovered_at=discovered_at or datetime.now(UTC),
        raw_payload=payload,
    )
