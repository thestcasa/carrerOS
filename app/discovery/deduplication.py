from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlsplit

from app.discovery.contracts import NormalizedJob


def normalize_fingerprint_value(value: str | None) -> str:
    if value is None:
        return ""
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", ascii_value.casefold()))


def semantic_description_fingerprint(description: str) -> str:
    normalized = normalize_fingerprint_value(description)
    return hashlib.sha256(normalized.encode()).hexdigest()


def job_duplicate_fingerprint(job: NormalizedJob) -> str:
    components = (
        job.source,
        job.external_job_id,
        job.requisition_id,
        str(job.application_url),
        job.company,
        job.normalized_title,
        job.location,
        semantic_description_fingerprint(job.description_normalized),
    )
    canonical = "\x1f".join(normalize_fingerprint_value(value) for value in components)
    return hashlib.sha256(canonical.encode()).hexdigest()


def application_duplicate_hash(
    *,
    candidate_id: str,
    company: str,
    title: str,
    location: str | None,
    requisition_id: str | None,
) -> str:
    canonical = "\x1f".join(
        normalize_fingerprint_value(value)
        for value in (candidate_id, company, title, location, requisition_id)
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def submission_identity_hash(
    *,
    candidate_id: str,
    company: str,
    title: str,
    location: str | None,
    requisition_id: str | None,
    application_url: str | None = None,
) -> str:
    """Return the strongest candidate-scoped identity available before application creation.

    A requisition ID is authoritative across renamed or reposted source records. When it is
    absent, fall back to the specification's candidate/company/title/location identity.
    """

    normalized_requisition = normalize_fingerprint_value(requisition_id)
    if not normalized_requisition:
        normalized_url = normalize_application_url(application_url)
        if normalized_url:
            canonical = "\x1f".join(
                normalize_fingerprint_value(value)
                for value in (candidate_id, company, normalized_url)
            )
            return hashlib.sha256(canonical.encode()).hexdigest()
        return application_duplicate_hash(
            candidate_id=candidate_id,
            company=company,
            title=title,
            location=location,
            requisition_id=None,
        )
    canonical = "\x1f".join(
        normalize_fingerprint_value(value)
        for value in (candidate_id, company, normalized_requisition)
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def normalize_application_url(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        return ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    path = parsed.path.rstrip("/") or "/"
    return f"https://{parsed.hostname.casefold()}{port}{path}"
