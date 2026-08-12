from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ProviderPlatform = Literal["greenhouse", "lever", "ashby"]

_SOURCE_KEY = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_JOBS = 1_000
_TIMEOUT_SECONDS = 10.0


class ProviderFetchError(ValueError):
    """A stable, body-free provider failure safe to persist on a workflow task."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ProviderHttpResponse:
    status_code: int
    final_url: str
    headers: Mapping[str, str]
    body: bytes


class ProviderTransport(Protocol):
    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
    ) -> ProviderHttpResponse: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class UrllibProviderTransport:
    """Bounded HTTPS transport which deliberately does not follow redirects."""

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
    ) -> ProviderHttpResponse:
        request = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "CareerOS/0.1"},
            method="GET",
        )
        opener = build_opener(_NoRedirectHandler())
        deadline = time.monotonic() + timeout_seconds
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                return ProviderHttpResponse(
                    status_code=response.status,
                    final_url=response.geturl(),
                    headers=dict(response.headers.items()),
                    body=_read_with_deadline(response, max_bytes, deadline),
                )
        except HTTPError as exc:
            return ProviderHttpResponse(
                status_code=exc.code,
                final_url=exc.geturl(),
                headers=dict(exc.headers.items()) if exc.headers is not None else {},
                body=b"",
            )
        except TimeoutError as exc:
            raise ProviderFetchError("provider_timeout", "Provider request timed out.") from exc
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise ProviderFetchError("provider_timeout", "Provider request timed out.") from exc
            raise ProviderFetchError(
                "provider_transport_error", "Provider request could not be completed."
            ) from exc
        except OSError as exc:
            raise ProviderFetchError(
                "provider_transport_error", "Provider request could not be completed."
            ) from exc


def _read_with_deadline(response: Any, max_bytes: int, deadline: float) -> bytes:
    content = bytearray()
    read_one = getattr(response, "read1", None)
    if not callable(read_one):
        raise ProviderFetchError(
            "provider_transport_error", "Provider response cannot be read safely."
        )
    while len(content) <= max_bytes:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProviderFetchError("provider_timeout", "Provider request timed out.")
        raw = getattr(getattr(response, "fp", None), "raw", None)
        socket = getattr(raw, "_sock", None)
        set_timeout = getattr(socket, "settimeout", None)
        if not callable(set_timeout):
            raise ProviderFetchError(
                "provider_transport_error", "Provider response cannot be bounded safely."
            )
        set_timeout(remaining)
        chunk = read_one(min(65_536, max_bytes + 1 - len(content)))
        if time.monotonic() >= deadline:
            raise ProviderFetchError("provider_timeout", "Provider request timed out.")
        if not chunk:
            break
        content.extend(chunk)
        is_closed = getattr(response, "isclosed", None)
        if callable(is_closed) and is_closed():
            break
    return bytes(content)


class FixtureProviderTransport:
    """Exact-URL transport for deterministic tests and offline fixtures."""

    def __init__(self, responses: Mapping[str, ProviderHttpResponse | Exception]) -> None:
        self._responses = dict(responses)
        self.requests: list[tuple[str, float, int]] = []

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        max_bytes: int,
    ) -> ProviderHttpResponse:
        self.requests.append((url, timeout_seconds, max_bytes))
        response = self._responses.get(url)
        if response is None:
            raise OSError("fixture response is missing")
        if isinstance(response, Exception):
            raise response
        return response


def provider_feed_url(platform: ProviderPlatform, source_key: str) -> str:
    if not _SOURCE_KEY.fullmatch(source_key):
        raise ProviderFetchError(
            "invalid_provider_source", "Provider source key contains invalid characters."
        )
    encoded = quote(source_key, safe="-_")
    if platform == "greenhouse":
        url = f"https://boards-api.greenhouse.io/v1/boards/{encoded}/jobs?content=true"
        expected_host = "boards-api.greenhouse.io"
    elif platform == "lever":
        url = f"https://api.lever.co/v0/postings/{encoded}?mode=json"
        expected_host = "api.lever.co"
    elif platform == "ashby":
        url = f"https://api.ashbyhq.com/posting-api/job-board/{encoded}"
        expected_host = "api.ashbyhq.com"
    else:
        raise ProviderFetchError("unsupported_provider", "Discovery provider is not supported.")

    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != expected_host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.fragment
    ):
        raise ProviderFetchError("invalid_provider_url", "Provider URL failed validation.")
    return url


class ProviderFeedClient:
    def __init__(
        self,
        transport: ProviderTransport | None = None,
        *,
        timeout_seconds: float = _TIMEOUT_SECONDS,
        max_response_bytes: int = _MAX_RESPONSE_BYTES,
        max_jobs: int = _MAX_JOBS,
    ) -> None:
        if timeout_seconds <= 0 or max_response_bytes < 1 or max_jobs < 1:
            raise ValueError("provider transport limits must be positive")
        self._transport = transport or UrllibProviderTransport()
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._max_jobs = max_jobs

    def fetch(self, platform: ProviderPlatform, source_key: str) -> tuple[dict[str, Any], ...]:
        url = provider_feed_url(platform, source_key)
        try:
            response = self._transport.fetch(
                url,
                timeout_seconds=self._timeout_seconds,
                max_bytes=self._max_response_bytes,
            )
        except ProviderFetchError:
            raise
        except TimeoutError as exc:
            raise ProviderFetchError("provider_timeout", "Provider request timed out.") from exc
        except Exception as exc:
            raise ProviderFetchError(
                "provider_transport_error", "Provider request could not be completed."
            ) from exc

        if response.final_url != url or 300 <= response.status_code < 400:
            raise ProviderFetchError(
                "provider_redirect_blocked",
                "Provider response redirected away from the exact feed.",
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderFetchError(
                "provider_http_status", "Provider returned a non-success HTTP status."
            )
        if len(response.body) > self._max_response_bytes:
            raise ProviderFetchError(
                "provider_response_too_large", "Provider response exceeded the byte limit."
            )
        if not _is_json_content_type(_header(response.headers, "content-type")):
            raise ProviderFetchError("provider_content_type", "Provider response was not JSON.")
        try:
            decoded = response.body.decode("utf-8")
            payload = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderFetchError(
                "provider_invalid_json", "Provider returned invalid JSON."
            ) from exc

        jobs = _extract_jobs(platform, payload)
        if len(jobs) > self._max_jobs:
            raise ProviderFetchError(
                "provider_job_limit_exceeded", "Provider response exceeded the job limit."
            )
        if not all(isinstance(item, dict) for item in jobs):
            raise ProviderFetchError(
                "provider_invalid_payload", "Provider response did not contain job objects."
            )
        return tuple(dict(item) for item in jobs)


def _extract_jobs(platform: ProviderPlatform, payload: Any) -> list[Any]:
    if platform == "lever":
        if not isinstance(payload, list):
            raise ProviderFetchError(
                "provider_invalid_payload", "Provider response did not contain a job list."
            )
        return payload
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ProviderFetchError(
            "provider_invalid_payload", "Provider response did not contain a job list."
        )
    jobs: list[Any] = payload["jobs"]
    return jobs


def _header(headers: Mapping[str, str], name: str) -> str | None:
    expected = name.casefold()
    return next((value for key, value in headers.items() if key.casefold() == expected), None)


def _is_json_content_type(value: str | None) -> bool:
    if value is None:
        return False
    media_type = value.partition(";")[0].strip().casefold()
    return media_type == "application/json" or (
        media_type.startswith("application/") and media_type.endswith("+json")
    )
