from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class UrlValidationResult:
    allowed: bool
    normalized_url: str | None
    reason: str | None


def validate_https_url(url: str, allowed_domains: tuple[str, ...]) -> UrlValidationResult:
    """Validate a network URL against exact hosts or their subdomains."""
    try:
        parsed = urlsplit(url.strip())
        port = parsed.port
    except ValueError:
        return UrlValidationResult(False, None, "malformed_url")
    hostname = parsed.hostname.casefold().rstrip(".") if parsed.hostname else None
    domains = tuple(domain.casefold().rstrip(".") for domain in allowed_domains)
    if parsed.scheme.casefold() != "https":
        return UrlValidationResult(False, None, "https_required")
    if not hostname or parsed.username is not None or parsed.password is not None:
        return UrlValidationResult(False, None, "invalid_authority")
    if parsed.fragment:
        return UrlValidationResult(False, None, "fragment_not_allowed")
    if not any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains):
        return UrlValidationResult(False, None, "domain_not_allowed")
    authority = hostname if port is None else f"{hostname}:{port}"
    path = parsed.path or "/"
    normalized = f"https://{authority}{path}"
    if parsed.query:
        normalized += f"?{parsed.query}"
    return UrlValidationResult(True, normalized, None)


@dataclass(frozen=True, slots=True)
class InjectionFinding:
    code: str
    excerpt: str


_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("instruction_override", re.compile(r"\bignore\s+(?:all\s+)?previous\s+instructions?\b", re.I)),
    (
        "secret_exfiltration",
        re.compile(
            r"\b(?:reveal|send|exfiltrate)\b.{0,50}"
            r"\b(?:secret|credential|api key|password|cookie)s?\b",
            re.I | re.S,
        ),
    ),
    (
        "policy_bypass",
        re.compile(
            r"\b(?:disable|bypass|skip)\b.{0,40}\b(?:logging|validation|safety|submission gate)\b",
            re.I | re.S,
        ),
    ),
    (
        "local_file_access",
        re.compile(
            r"\b(?:upload|read|open)\b.{0,40}\b(?:local files?|/etc/|home directory)\b", re.I | re.S
        ),
    ),
    (
        "hidden_ats_content",
        re.compile(r"\b(?:white[- ]on[- ]white|zero[- ]size|hidden text|keyword stuffing)\b", re.I),
    ),
)


def scan_prompt_injection(text: str) -> tuple[InjectionFinding, ...]:
    findings: list[InjectionFinding] = []
    for code, pattern in _INJECTION_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            excerpt = " ".join(match.group(0).split())[:120]
            findings.append(InjectionFinding(code=code, excerpt=excerpt))
    return tuple(findings)
