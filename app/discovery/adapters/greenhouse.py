from __future__ import annotations

from datetime import datetime
from typing import Any

from app.discovery.adapters.base import build_job, nested_string, required_string
from app.discovery.contracts import NormalizedJob


class GreenhouseAdapter:
    platform = "greenhouse"

    def parse(
        self,
        payload: dict[str, Any],
        *,
        company: str,
        company_domain: str,
        discovered_at: datetime | None = None,
    ) -> NormalizedJob:
        url = required_string(payload, "absolute_url")
        return build_job(
            platform=self.platform,
            payload=payload,
            external_id=required_string(payload, "id"),
            requisition_id=str(payload["internal_job_id"])
            if payload.get("internal_job_id") is not None
            else None,
            title=required_string(payload, "title"),
            description=required_string(payload, "content"),
            location=nested_string(payload, "location", "name"),
            source_url=url,
            application_url=url,
            allowed_domains=("greenhouse.io", "greenhouse.com"),
            company=company,
            company_domain=company_domain,
            posted_at=None,
            discovered_at=discovered_at,
        )
