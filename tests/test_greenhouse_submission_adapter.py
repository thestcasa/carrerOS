from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from app.domain.enums import ApplicationState
from app.submission import (
    ControlledGreenhouseFormPayload,
    ControlledSubmissionError,
    ControlledSubmissionRequest,
    ControlledSubmissionUncertainError,
    GreenhouseControlledAdapter,
)
from app.submission_gate import FinalClickPermit, FinalClickProof, SubmissionGate

_TARGET = "https://greenhouse.fixture.invalid/fictional/jobs/42"
_PNG = b"\x89PNG\r\n\x1a\nfictional-confirmation"


@dataclass
class _Locator:
    page: _Page
    selector: str

    def count(self) -> int:
        return self.page.counts.get(self.selector, 0)

    def get_attribute(self, name: str) -> str | None:
        return self.page.attributes.get((self.selector, name))

    def click(self, *, timeout: float) -> None:
        assert timeout == 5_000
        self.page.clicks += 1
        if self.page.click_error:
            raise RuntimeError("fictional browser interruption")

    def fill(self, value: str) -> None:
        self.page.values[self.selector] = value

    def input_value(self) -> str:
        return self.page.values.get(self.selector, "")

    def set_input_files(self, files: str) -> None:
        self.page.values[self.selector] = files

    def text_content(self) -> str | None:
        return self.page.texts.get(self.selector)


class _Page:
    def __init__(self) -> None:
        self.url = _TARGET
        self.clicks = 0
        self.click_error = False
        self.counts = {selector: 1 for selector in GreenhouseControlledAdapter.selectors()}
        self.counts["#application_confirmation"] = 1
        self.attributes = {("form#application_form", "action"): "/fictional/jobs/42/applications"}
        self.texts = {"#application_confirmation": "Fictional application received"}
        self.values = {
            "form#application_form #first_name": "Fictional",
            "form#application_form #last_name": "Candidate",
            "form#application_form #email": "candidate@fictional.invalid",
            "form#application_form input[type='file'][name='resume']": (
                "/tmp/fictional-resume.pdf"
            ),
        }

    def locator(self, selector: str) -> _Locator:
        return _Locator(self, selector)

    def wait_for_load_state(self, state: str, *, timeout: float) -> None:
        assert state == "domcontentloaded"
        assert timeout == 10_000

    def screenshot(self, **kwargs: Any) -> bytes:
        assert kwargs == {"type": "png", "full_page": True}
        return _PNG

    def content(self) -> str:
        return "<!doctype html><p>Fictional confirmation</p>"


def _adapter(*, enabled: bool) -> GreenhouseControlledAdapter:
    return GreenhouseControlledAdapter(
        enabled=enabled,
        allowed_hosts=frozenset({"greenhouse.fixture.invalid"}),
    )


def _request(fingerprint: str) -> ControlledSubmissionRequest:
    form = ControlledGreenhouseFormPayload(
        first_name="Fictional",
        last_name="Candidate",
        email="candidate@fictional.invalid",
        resume_path=Path("/tmp/fictional-resume.pdf"),
        resume_sha256="b" * 64,
    )
    return ControlledSubmissionRequest(
        attempt_id=UUID("00000000-0000-0000-0000-000000000001"),
        candidate_id="fictional_candidate",
        application_id=UUID("00000000-0000-0000-0000-000000000002"),
        authorization_id=UUID("00000000-0000-0000-0000-000000000003"),
        target_url=_TARGET,
        package_sha256="a" * 64,
        form=form,
        expected_form_payload_sha256=form.sha256(),
        expected_form_fingerprint=fingerprint,
    )


def _permit(request: ControlledSubmissionRequest) -> FinalClickPermit:
    click_nonce = b"f" * 32
    now = datetime.now(UTC)
    return SubmissionGate().issue_final_click_permit(
        FinalClickProof(
            candidate_id=request.candidate_id,
            application_id=request.application_id,
            authorization_id=request.authorization_id,
            attempt_id=request.attempt_id,
            application_state=ApplicationState.SUBMITTING,
            attempt_status="click_authorized",
            authorization_consumed_at=now,
            click_boundary_entered_at=now,
            click_nonce_sha256=hashlib.sha256(click_nonce).hexdigest(),
        ),
        click_nonce,
    )


def test_greenhouse_controlled_adapter_is_default_disabled() -> None:
    page = _Page()
    inspection = _adapter(enabled=False).inspect(page, _TARGET)

    with pytest.raises(ControlledSubmissionError, match="disabled"):
        request = _request(inspection.form_fingerprint)
        _adapter(enabled=False).execute(page, request, _permit(request))

    assert page.clicks == 0


def test_exact_greenhouse_fingerprint_clicks_once_and_requires_confirmation() -> None:
    page = _Page()
    adapter = _adapter(enabled=True)
    inspection = adapter.inspect(page, _TARGET)

    request = _request(inspection.form_fingerprint)
    result = adapter.execute(page, request, _permit(request))

    assert page.clicks == 1
    assert result.click_invoked
    assert result.confirmation_detected
    assert result.confirmation_reference is not None
    assert result.screenshot_png == _PNG


def test_network_post_is_armed_only_after_the_gate_permit_is_consumed() -> None:
    page = _Page()
    adapter = _adapter(enabled=True)
    request = _request(adapter.inspect(page, _TARGET).form_fingerprint)
    permit = _permit(request)
    post_authorizations = 0

    def authorize_single_post() -> None:
        nonlocal post_authorizations
        post_authorizations += 1
        with pytest.raises(PermissionError, match="already consumed"):
            permit.consume(
                candidate_id=request.candidate_id,
                application_id=request.application_id,
                authorization_id=request.authorization_id,
                attempt_id=request.attempt_id,
            )

    adapter.execute(
        page,
        request,
        permit,
        authorize_single_post=authorize_single_post,
    )

    assert post_authorizations == 1
    assert page.clicks == 1


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_field", "fingerprint"),
        ("captcha", "human verification"),
        ("otp", "human verification"),
        ("submit_ambiguous", "ambiguous"),
        ("unsupported_control", "unsupported form control"),
    ],
)
def test_greenhouse_form_drift_and_human_verification_deny_before_click(
    mutation: str, message: str
) -> None:
    page = _Page()
    if mutation == "missing_field":
        page.counts["form#application_form #email"] = 0
    elif mutation == "captcha":
        page.counts["iframe[src*='recaptcha']"] = 1
    elif mutation == "otp":
        page.counts["input[autocomplete='one-time-code']"] = 1
    elif mutation == "unsupported_control":
        page.counts[GreenhouseControlledAdapter.unsupported_control_selector()] = 1
    else:
        page.counts["form#application_form #submit_app"] = 2

    with pytest.raises(ControlledSubmissionError, match=message):
        _adapter(enabled=True).inspect(page, _TARGET)

    assert page.clicks == 0


def test_greenhouse_form_values_are_exactly_populated_and_rechecked() -> None:
    page = _Page()
    adapter = _adapter(enabled=True)
    request = _request(adapter.inspect(page, _TARGET).form_fingerprint)
    page.values.clear()

    adapter.populate(page, request.form)
    assert page.values["form#application_form #email"] == "candidate@fictional.invalid"

    page.values["form#application_form #last_name"] = "Drifted"
    with pytest.raises(ControlledSubmissionError, match="values changed"):
        adapter.execute(page, request, _permit(request))
    assert page.clicks == 0


def test_click_interruption_is_uncertain_and_never_retried_by_adapter() -> None:
    page = _Page()
    adapter = _adapter(enabled=True)
    fingerprint = adapter.inspect(page, _TARGET).form_fingerprint
    page.click_error = True

    with pytest.raises(ControlledSubmissionUncertainError) as failure:
        request = _request(fingerprint)
        adapter.execute(page, request, _permit(request))

    assert failure.value.click_may_have_occurred
    assert page.clicks == 1


def test_final_click_permit_cannot_be_replayed() -> None:
    page = _Page()
    adapter = _adapter(enabled=True)
    request = _request(adapter.inspect(page, _TARGET).form_fingerprint)
    permit = _permit(request)

    adapter.execute(page, request, permit)
    with pytest.raises(PermissionError, match="already consumed"):
        adapter.execute(page, request, permit)

    assert page.clicks == 1


@pytest.mark.parametrize(
    "target_url",
    [
        "http://greenhouse.fixture.invalid/fictional/jobs/42",
        "https://greenhouse.fixture.invalid:8443/fictional/jobs/42",
        "https://user@greenhouse.fixture.invalid/fictional/jobs/42",
        "https://greenhouse.fixture.invalid/fictional/jobs/42?token=secret",
        "https://greenhouse.fixture.invalid/fictional/jobs/42#apply",
    ],
)
def test_greenhouse_target_policy_rejects_unsafe_urls(target_url: str) -> None:
    with pytest.raises(ControlledSubmissionError, match="not allowed"):
        _adapter(enabled=True).validate_target(target_url)


def test_missing_confirmation_is_reported_without_a_second_click() -> None:
    page = _Page()
    page.counts["#application_confirmation"] = 0
    adapter = _adapter(enabled=True)
    request = _request(adapter.inspect(page, _TARGET).form_fingerprint)

    result = adapter.execute(page, request, _permit(request))

    assert page.clicks == 1
    assert not result.confirmation_detected
    assert result.confirmation_reference is None
