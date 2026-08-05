from __future__ import annotations

import hashlib
import re
import unicodedata

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
