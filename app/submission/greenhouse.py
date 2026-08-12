from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from typing import Literal, Protocol
from urllib.parse import urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.submission.contracts import (
    ControlledGreenhouseFormPayload,
    ControlledSubmissionError,
    ControlledSubmissionRequest,
    ControlledSubmissionResult,
    ControlledSubmissionUncertainError,
    GreenhouseFormInspection,
)
from app.submission_gate import FinalClickPermit


class _Locator(Protocol):
    def count(self) -> int: ...
    def get_attribute(self, name: str) -> str | None: ...
    def click(self, *, timeout: float) -> None: ...
    def fill(self, value: str) -> None: ...
    def input_value(self) -> str: ...
    def set_input_files(self, files: str) -> None: ...
    def text_content(self) -> str | None: ...


class SubmissionPage(Protocol):
    @property
    def url(self) -> str: ...
    def locator(self, selector: str) -> _Locator: ...
    def wait_for_load_state(self, state: str, *, timeout: float) -> None: ...
    def screenshot(self, *, type: Literal["png"], full_page: bool) -> bytes: ...
    def content(self) -> str: ...


class GreenhouseControlledAdapter:
    """Narrow final-click adapter for one explicitly fingerprinted Greenhouse form pattern."""

    VERSION = "greenhouse_controlled_v1"
    FORM_PATTERN = "basic_identity_resume_v1"
    _FORM_SELECTOR = "form#application_form"
    _SUBMIT_SELECTOR = "form#application_form #submit_app"
    _REQUIRED_SELECTORS = (
        "form#application_form #first_name",
        "form#application_form #last_name",
        "form#application_form #email",
        "form#application_form input[type='file'][name='resume']",
    )
    _CAPTCHA_SELECTORS = (
        "iframe[src*='recaptcha']",
        "iframe[src*='hcaptcha']",
        "[data-sitekey]",
    )
    _OTP_SELECTOR = "input[autocomplete='one-time-code']"
    _UNSUPPORTED_CONTROL_SELECTOR = (
        "form#application_form input:not([type='hidden']):not(#first_name):not(#last_name)"
        ":not(#email):not([type='file'][name='resume']):not(#submit_app), "
        "form#application_form select, form#application_form textarea"
    )
    _CONFIRMATION_SELECTORS = (
        "#application_confirmation",
        "[data-qa='application-confirmation']",
    )

    def __init__(
        self,
        *,
        enabled: bool = False,
        allowed_hosts: frozenset[str] = frozenset(
            {"boards.greenhouse.io", "job-boards.greenhouse.io"}
        ),
    ) -> None:
        if not allowed_hosts or any(not host or "/" in host for host in allowed_hosts):
            raise ValueError("controlled Greenhouse hosts must be explicit hostnames")
        self._enabled = enabled
        self._allowed_hosts = allowed_hosts

    @property
    def destination_policy_sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "adapter": self.VERSION,
                    "allowed_hosts": sorted(self._allowed_hosts),
                    "https_required": True,
                    "same_origin_form_action": True,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    def inspect(self, page: SubmissionPage, target_url: str) -> GreenhouseFormInspection:
        target = self._validated_url(target_url)
        current = self._validated_url(page.url)
        if current != target:
            raise ControlledSubmissionError("Greenhouse page URL changed before final validation")
        form = page.locator(self._FORM_SELECTOR)
        if form.count() != 1:
            raise ControlledSubmissionError("tested Greenhouse application form was not found")
        form_action_value = form.get_attribute("action")
        if not form_action_value:
            raise ControlledSubmissionError("Greenhouse form action is missing")
        form_action = self._validated_url(form_action_value, base=target)
        if urlsplit(form_action).hostname != urlsplit(target).hostname:
            raise ControlledSubmissionError("Greenhouse form action changed origin")
        missing = tuple(
            selector for selector in self._REQUIRED_SELECTORS if page.locator(selector).count() != 1
        )
        if missing:
            raise ControlledSubmissionError("Greenhouse form fingerprint has changed")
        if page.locator(self._UNSUPPORTED_CONTROL_SELECTOR).count() > 0:
            raise ControlledSubmissionError(
                "Greenhouse form has an unsupported form control",
                category="unsupported_form_control",
                human_action_kind="novel_required_field",
            )
        submit_count = page.locator(self._SUBMIT_SELECTOR).count()
        if submit_count != 1:
            raise ControlledSubmissionError("Greenhouse final submit control is ambiguous")
        human_verification = self._human_verification_kind(page)
        if human_verification is not None:
            raise ControlledSubmissionError(
                "human verification blocks controlled submission",
                category="human_verification",
                human_action_kind=human_verification,
            )
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "adapter": self.VERSION,
                    "form_pattern": self.FORM_PATTERN,
                    "required_selectors": self._REQUIRED_SELECTORS,
                    "unsupported_control_selector": self._UNSUPPORTED_CONTROL_SELECTOR,
                    "submit_selector": self._SUBMIT_SELECTOR,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return GreenhouseFormInspection(
            target_url=target,
            form_action=form_action,
            form_fingerprint=fingerprint,
            required_selectors=self._REQUIRED_SELECTORS,
            submit_selector=self._SUBMIT_SELECTOR,
            submit_control_count=1,
            human_verification_present=False,
        )

    def validate_target(self, target_url: str) -> str:
        return self._validated_url(target_url)

    def populate(self, page: SubmissionPage, payload: ControlledGreenhouseFormPayload) -> None:
        values = {
            "form#application_form #first_name": payload.first_name,
            "form#application_form #last_name": payload.last_name,
            "form#application_form #email": payload.email,
        }
        for selector, value in values.items():
            locator = page.locator(selector)
            if locator.count() != 1:
                raise ControlledSubmissionError("Greenhouse form fingerprint has changed")
            locator.fill(value)
            if locator.input_value() != value:
                raise ControlledSubmissionError("Greenhouse form did not retain an exact value")
        resume = page.locator("form#application_form input[type='file'][name='resume']")
        if resume.count() != 1:
            raise ControlledSubmissionError("Greenhouse form fingerprint has changed")
        resume.set_input_files(str(payload.resume_path.resolve()))
        if not resume.input_value().endswith(payload.resume_path.name):
            raise ControlledSubmissionError("Greenhouse form did not retain the reviewed resume")

    def verify_populated(
        self, page: SubmissionPage, payload: ControlledGreenhouseFormPayload
    ) -> None:
        expected = {
            "form#application_form #first_name": payload.first_name,
            "form#application_form #last_name": payload.last_name,
            "form#application_form #email": payload.email,
        }
        if any(
            page.locator(selector).input_value() != value for selector, value in expected.items()
        ):
            raise ControlledSubmissionError("Greenhouse form values changed before click")
        resume = page.locator(
            "form#application_form input[type='file'][name='resume']"
        ).input_value()
        if not resume.endswith(payload.resume_path.name):
            raise ControlledSubmissionError("Greenhouse resume changed before click")

    def execute(
        self,
        page: SubmissionPage,
        request: ControlledSubmissionRequest,
        permit: FinalClickPermit,
        *,
        authorize_single_post: Callable[[], None] | None = None,
    ) -> ControlledSubmissionResult:
        if not self._enabled:
            raise ControlledSubmissionError("controlled Greenhouse submission is disabled")
        inspection = self.inspect(page, request.target_url)
        if inspection.form_fingerprint != request.expected_form_fingerprint:
            raise ControlledSubmissionError("Greenhouse form fingerprint changed before click")
        if request.form.sha256() != request.expected_form_payload_sha256:
            raise ControlledSubmissionError("Greenhouse form payload changed before click")
        self.verify_populated(page, request.form)
        submit = page.locator(self._SUBMIT_SELECTOR)
        permit.consume(
            candidate_id=request.candidate_id,
            application_id=request.application_id,
            authorization_id=request.authorization_id,
            attempt_id=request.attempt_id,
        )
        if authorize_single_post is not None:
            authorize_single_post()
        try:
            submit.click(timeout=5_000)
            page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except (PlaywrightTimeoutError, RuntimeError) as exc:
            raise ControlledSubmissionUncertainError(
                "Greenhouse click outcome is uncertain; human review is required"
            ) from exc
        confirmation_reference = self._confirmation_reference(page)
        try:
            screenshot = page.screenshot(type="png", full_page=True)
            final_page_html = page.content().encode()
        except (PlaywrightTimeoutError, RuntimeError) as exc:
            raise ControlledSubmissionUncertainError(
                "Greenhouse confirmation capture is uncertain; human review is required"
            ) from exc
        return ControlledSubmissionResult(
            attempt_id=request.attempt_id,
            click_invoked=True,
            confirmation_detected=confirmation_reference is not None,
            confirmation_reference=confirmation_reference,
            final_url=self._validated_url(page.url),
            screenshot_png=screenshot,
            final_page_html=final_page_html,
        )

    def _validated_url(self, value: str, *, base: str | None = None) -> str:
        if base is not None and value.startswith("/"):
            parsed_base = urlsplit(base)
            value = f"{parsed_base.scheme}://{parsed_base.hostname}{value}"
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in self._allowed_hosts
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ControlledSubmissionError("Greenhouse controlled-submission URL is not allowed")
        port = parsed.port
        if port not in {None, 443}:
            raise ControlledSubmissionError("Greenhouse controlled-submission port is not allowed")
        path = parsed.path or "/"
        return f"https://{parsed.hostname}{path}"

    def _human_verification_kind(self, page: SubmissionPage) -> Literal["captcha", "otp"] | None:
        if any(page.locator(selector).count() > 0 for selector in self._CAPTCHA_SELECTORS):
            return "captcha"
        if page.locator(self._OTP_SELECTOR).count() > 0:
            return "otp"
        return None

    def _confirmation_reference(self, page: SubmissionPage) -> str | None:
        for selector in self._CONFIRMATION_SELECTORS:
            locator = page.locator(selector)
            if locator.count() != 1:
                continue
            text = " ".join((locator.text_content() or "").split())
            if text:
                return hashlib.sha256(text.encode()).hexdigest()[:32]
        return None

    @classmethod
    def selectors(cls) -> Iterable[str]:
        return (*cls._REQUIRED_SELECTORS, cls._FORM_SELECTOR, cls._SUBMIT_SELECTOR)

    @classmethod
    def unsupported_control_selector(cls) -> str:
        return cls._UNSUPPORTED_CONTROL_SELECTOR
