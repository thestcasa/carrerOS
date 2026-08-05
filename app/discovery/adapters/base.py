from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from typing import Any

from app.discovery.contracts import NormalizedJob
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
        title=title,
        normalized_title=" ".join(title.casefold().split()),
        location=location,
        description_raw=description,
        description_normalized=normalized_description,
        posted_at=posted_at,
        source_url=validated_url(source_url, allowed_domains),
        application_url=validated_url(application_url, allowed_domains),
        ats_platform=platform,
        discovered_at=discovered_at or datetime.now(UTC),
        raw_payload=payload,
    )
