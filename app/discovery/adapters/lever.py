from __future__ import annotations

from datetime import datetime
from typing import Any

from app.discovery.adapters.base import build_job, nested_string, parse_datetime, required_string
from app.discovery.contracts import NormalizedJob


class LeverAdapter:
    platform = "lever"

    def parse(
        self,
        payload: dict[str, Any],
        *,
        company: str,
        company_domain: str,
        discovered_at: datetime | None = None,
    ) -> NormalizedJob:
        source_url = required_string(payload, "hostedUrl")
        application_url = str(payload.get("applyUrl") or source_url)
        description = str(payload.get("descriptionPlain") or payload.get("description") or "")
        return build_job(
            platform=self.platform,
            payload=payload,
            external_id=required_string(payload, "id"),
            title=required_string(payload, "text"),
            description=description,
            location=nested_string(payload, "categories", "location"),
            source_url=source_url,
            application_url=application_url,
            allowed_domains=("lever.co",),
            company=company,
            company_domain=company_domain,
            posted_at=parse_datetime(payload.get("createdAt")),
            discovered_at=discovered_at,
        )
