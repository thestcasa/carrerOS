from __future__ import annotations

from datetime import datetime
from typing import Any

from app.discovery.adapters.base import build_job, optional_string, parse_datetime, required_string
from app.discovery.contracts import NormalizedJob


class AshbyAdapter:
    platform = "ashby"

    def parse(
        self,
        payload: dict[str, Any],
        *,
        company: str,
        company_domain: str,
        discovered_at: datetime | None = None,
    ) -> NormalizedJob:
        source_url = required_string(payload, "jobUrl")
        application_url = str(payload.get("applyUrl") or source_url)
        description = str(payload.get("descriptionPlain") or payload.get("descriptionHtml") or "")
        return build_job(
            platform=self.platform,
            payload=payload,
            external_id=required_string(payload, "id"),
            title=required_string(payload, "title"),
            description=description,
            location=str(payload["location"]).strip() if payload.get("location") else None,
            source_url=source_url,
            application_url=application_url,
            allowed_domains=("ashbyhq.com",),
            company=company,
            company_domain=company_domain,
            posted_at=parse_datetime(payload.get("publishedAt")),
            discovered_at=discovered_at,
            remote_policy=optional_string(payload, "workplaceType"),
            employment_type=optional_string(payload, "employmentType"),
            seniority=optional_string(payload, "seniority"),
            team=optional_string(payload, "team") or optional_string(payload, "department"),
        )
