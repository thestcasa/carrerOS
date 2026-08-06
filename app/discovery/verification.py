from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from app.discovery.adapters import AshbyAdapter, GreenhouseAdapter, LeverAdapter
from app.discovery.contracts import JobPayloadAdapter
from app.discovery.deduplication import normalize_application_url
from app.discovery.providers import ProviderFeedClient, ProviderFetchError
from app.domain.models import GlobalJob


class VerificationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["open", "closed", "error"]
    checked_at: datetime
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source: str
    reason: str
    current_application_url: str | None = None
    provider_payload_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class JobSourceVerifier(Protocol):
    def verify(self, job: GlobalJob, *, checked_at: datetime | None = None) -> VerificationEvidence:
        """Revalidate one opening against its official provider source."""


class ProviderJobSourceVerifier:
    """Fail-closed, bounded revalidation against the official ATS board feed."""

    def __init__(self, client: ProviderFeedClient | None = None) -> None:
        self._client = client or ProviderFeedClient()
        self._adapters: dict[str, JobPayloadAdapter] = {
            "greenhouse": GreenhouseAdapter(),
            "lever": LeverAdapter(),
            "ashby": AshbyAdapter(),
        }

    def verify(self, job: GlobalJob, *, checked_at: datetime | None = None) -> VerificationEvidence:
        now = checked_at or datetime.now(UTC)
        platform = job.ats_platform
        if platform not in self._adapters:
            return self._evidence(job, now, "error", "unsupported_provider", None, None)
        source_key = _source_key(platform, job.url)
        if source_key is None:
            return self._evidence(job, now, "error", "invalid_provider_source", None, None)
        try:
            payloads = self._client.fetch(platform, source_key)  # type: ignore[arg-type]
        except ProviderFetchError as exc:
            return self._evidence(job, now, "error", exc.code, None, None)

        payload = next((item for item in payloads if _matches(job, item)), None)
        if payload is None:
            return self._evidence(job, now, "closed", "opening_absent_from_feed", None, None)
        try:
            normalized = self._adapters[platform].parse(
                payload,
                company=job.company,
                company_domain=job.company_domain or "invalid.invalid",
                discovered_at=now,
            )
        except ValueError:
            return self._evidence(job, now, "error", "invalid_provider_payload", payload, None)
        current_application_url = str(normalized.application_url)
        if normalize_application_url(current_application_url) != normalize_application_url(
            job.application_url
        ):
            return self._evidence(
                job,
                now,
                "error",
                "application_url_changed",
                payload,
                current_application_url,
            )
        if job.deadline is not None:
            deadline = (
                job.deadline
                if job.deadline.tzinfo is not None
                else job.deadline.replace(tzinfo=UTC)
            )
            if deadline <= now:
                return self._evidence(
                    job, now, "closed", "application_deadline_passed", payload, None
                )
        return self._evidence(
            job,
            now,
            "open",
            "official_provider_feed_match",
            payload,
            current_application_url,
        )

    @staticmethod
    def _evidence(
        job: GlobalJob,
        checked_at: datetime,
        status: Literal["open", "closed", "error"],
        reason: str,
        payload: dict[str, Any] | None,
        application_url: str | None,
    ) -> VerificationEvidence:
        canonical = json.dumps(
            {
                "application_url": application_url,
                "checked_at": checked_at.isoformat(),
                "external_id": job.external_id,
                "payload": payload,
                "reason": reason,
                "source": job.source,
                "status": status,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        payload_sha256 = (
            hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if payload is not None
            else None
        )
        return VerificationEvidence(
            status=status,
            checked_at=checked_at,
            evidence_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
            source=job.source,
            reason=reason,
            current_application_url=application_url,
            provider_payload_sha256=payload_sha256,
        )


class StoredFixtureJobSourceVerifier:
    """Deterministic verifier for local fixtures; never configured by the production app."""

    def __init__(self, status: Literal["open", "closed", "error"] = "open") -> None:
        self._status = status

    def verify(self, job: GlobalJob, *, checked_at: datetime | None = None) -> VerificationEvidence:
        now = checked_at or datetime.now(UTC)
        reason = {
            "open": "offline_fixture_open",
            "closed": "offline_fixture_closed",
            "error": "offline_fixture_error",
        }[self._status]
        return ProviderJobSourceVerifier._evidence(
            job,
            now,
            self._status,
            reason,
            job.raw_payload,
            job.application_url if self._status == "open" else None,
        )


def apply_verification(job: GlobalJob, evidence: VerificationEvidence) -> None:
    job.verification_status = evidence.status
    job.verification_checked_at = evidence.checked_at
    job.verification_evidence_sha256 = evidence.evidence_sha256
    job.verification_evidence = evidence.model_dump(mode="json")
    job.verified_open_at = evidence.checked_at if evidence.status == "open" else None


def _matches(job: GlobalJob, payload: dict[str, object]) -> bool:
    external_id = payload.get("id")
    if external_id is not None and str(external_id) == job.external_id:
        return True
    requisition_id = payload.get("internal_job_id")
    return (
        job.requisition_id is not None
        and requisition_id is not None
        and str(requisition_id) == job.requisition_id
    )


def _source_key(platform: str, source_url: str) -> str | None:
    parsed = urlsplit(source_url)
    host = (parsed.hostname or "").casefold()
    expected_hosts: dict[str, set[str]] = {
        "greenhouse": {"boards.greenhouse.io", "job-boards.greenhouse.io"},
        "lever": {"jobs.lever.co"},
        "ashby": {"jobs.ashbyhq.com"},
    }
    if parsed.scheme != "https" or host not in expected_hosts.get(platform, set()):
        return None
    components = tuple(component for component in parsed.path.split("/") if component)
    return components[0] if components else None
