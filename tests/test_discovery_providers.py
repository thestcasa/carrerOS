from __future__ import annotations

import json

import pytest

from app.discovery.providers import (
    FixtureProviderTransport,
    ProviderFeedClient,
    ProviderFetchError,
    ProviderHttpResponse,
    _read_with_deadline,
    provider_feed_url,
)


def _response(
    url: str,
    payload: object,
    *,
    status_code: int = 200,
    content_type: str = "application/json; charset=utf-8",
    final_url: str | None = None,
) -> ProviderHttpResponse:
    return ProviderHttpResponse(
        status_code=status_code,
        final_url=final_url or url,
        headers={"Content-Type": content_type},
        body=json.dumps(payload).encode(),
    )


@pytest.mark.parametrize(
    ("platform", "source_key", "expected"),
    [
        (
            "greenhouse",
            "fictional-board",
            "https://boards-api.greenhouse.io/v1/boards/fictional-board/jobs?content=true",
        ),
        (
            "lever",
            "fictional_site",
            "https://api.lever.co/v0/postings/fictional_site?mode=json",
        ),
        (
            "ashby",
            "FictionalBoard",
            "https://api.ashbyhq.com/posting-api/job-board/FictionalBoard",
        ),
    ],
)
def test_provider_urls_are_exact_https_allowlisted_paths(
    platform: str, source_key: str, expected: str
) -> None:
    assert provider_feed_url(platform, source_key) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "source_key",
    (
        "https://evil.invalid/jobs",
        "user:password@example",
        "board#fragment",
        "../board",
        "board?token=secret",
        "",
    ),
)
def test_provider_source_rejects_credentials_fragments_and_path_escape(source_key: str) -> None:
    with pytest.raises(ProviderFetchError) as error:
        provider_feed_url("greenhouse", source_key)
    assert error.value.code == "invalid_provider_source"


@pytest.mark.parametrize(
    ("platform", "payload", "expected"),
    [
        ("greenhouse", {"jobs": [{"id": 1}, {"id": 2}]}, ({"id": 1}, {"id": 2})),
        ("lever", [{"id": "one"}], ({"id": "one"},)),
        ("ashby", {"jobs": [{"id": "job-one"}]}, ({"id": "job-one"},)),
    ],
)
def test_client_extracts_provider_payload_tuples_with_injected_transport(
    platform: str, payload: object, expected: tuple[dict[str, object], ...]
) -> None:
    url = provider_feed_url(platform, "fictional")  # type: ignore[arg-type]
    transport = FixtureProviderTransport({url: _response(url, payload)})

    result = ProviderFeedClient(
        transport, timeout_seconds=3.5, max_response_bytes=4_096, max_jobs=10
    ).fetch(platform, "fictional")  # type: ignore[arg-type]

    assert result == expected
    assert transport.requests == [(url, 3.5, 4_096)]


def test_client_rejects_redirect_even_when_final_response_is_successful() -> None:
    url = provider_feed_url("greenhouse", "fictional")
    transport = FixtureProviderTransport(
        {url: _response(url, {"jobs": []}, final_url="https://evil.invalid/jobs")}
    )

    with pytest.raises(ProviderFetchError) as error:
        ProviderFeedClient(transport).fetch("greenhouse", "fictional")
    assert error.value.code == "provider_redirect_blocked"


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (
            ProviderHttpResponse(
                status_code=302,
                final_url=provider_feed_url("lever", "fictional"),
                headers={"Content-Type": "application/json"},
                body=b"[]",
            ),
            "provider_redirect_blocked",
        ),
        (
            ProviderHttpResponse(
                status_code=503,
                final_url=provider_feed_url("lever", "fictional"),
                headers={"Content-Type": "application/json"},
                body=b"[]",
            ),
            "provider_http_status",
        ),
        (
            ProviderHttpResponse(
                status_code=200,
                final_url=provider_feed_url("lever", "fictional"),
                headers={"Content-Type": "text/html"},
                body=b"[]",
            ),
            "provider_content_type",
        ),
        (
            ProviderHttpResponse(
                status_code=200,
                final_url=provider_feed_url("lever", "fictional"),
                headers={"Content-Type": "application/json"},
                body=b"not json",
            ),
            "provider_invalid_json",
        ),
    ],
)
def test_client_reports_stable_response_errors(
    response: ProviderHttpResponse, expected_code: str
) -> None:
    url = provider_feed_url("lever", "fictional")

    with pytest.raises(ProviderFetchError) as error:
        ProviderFeedClient(FixtureProviderTransport({url: response})).fetch("lever", "fictional")
    assert error.value.code == expected_code


def test_client_enforces_response_byte_and_job_limits() -> None:
    url = provider_feed_url("greenhouse", "fictional")
    too_large = ProviderHttpResponse(
        status_code=200,
        final_url=url,
        headers={"Content-Type": "application/json"},
        body=b'{{"jobs":[]}}' + b" " * 40,
    )
    too_many = _response(url, {"jobs": [{"id": 1}, {"id": 2}]})

    with pytest.raises(ProviderFetchError) as bytes_error:
        ProviderFeedClient(FixtureProviderTransport({url: too_large}), max_response_bytes=32).fetch(
            "greenhouse", "fictional"
        )
    assert bytes_error.value.code == "provider_response_too_large"

    with pytest.raises(ProviderFetchError) as jobs_error:
        ProviderFeedClient(FixtureProviderTransport({url: too_many}), max_jobs=1).fetch(
            "greenhouse", "fictional"
        )
    assert jobs_error.value.code == "provider_job_limit_exceeded"


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"jobs": "not-a-list"},
        {"jobs": ["not-an-object"]},
    ),
)
def test_client_rejects_malformed_provider_shapes(payload: object) -> None:
    url = provider_feed_url("ashby", "fictional")

    with pytest.raises(ProviderFetchError) as error:
        ProviderFeedClient(FixtureProviderTransport({url: _response(url, payload)})).fetch(
            "ashby", "fictional"
        )
    assert error.value.code == "provider_invalid_payload"


@pytest.mark.parametrize(
    ("exception", "expected_code"),
    [(TimeoutError(), "provider_timeout"), (OSError(), "provider_transport_error")],
)
def test_client_normalizes_timeout_and_transport_failures(
    exception: Exception, expected_code: str
) -> None:
    url = provider_feed_url("lever", "fictional")

    with pytest.raises(ProviderFetchError) as error:
        ProviderFeedClient(FixtureProviderTransport({url: exception})).fetch("lever", "fictional")
    assert error.value.code == expected_code


def test_response_reader_enforces_absolute_deadline_after_each_raw_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Socket:
        def settimeout(self, remaining: float) -> None:
            assert remaining == 0.5

    class Raw:
        _sock = Socket()

    class File:
        raw = Raw()

    class SlowResponse:
        fp = File()

        def read1(self, amount: int) -> bytes:
            assert amount > 0
            return b"x"

    ticks = iter((0.5, 1.1))
    monkeypatch.setattr("app.discovery.providers.time.monotonic", lambda: next(ticks))

    with pytest.raises(ProviderFetchError) as error:
        _read_with_deadline(SlowResponse(), 8, 1.0)
    assert error.value.code == "provider_timeout"
