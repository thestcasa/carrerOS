from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from app.submission.contracts import ControlledGreenhouseFormPayload
from app.submission.greenhouse import GreenhouseControlledAdapter


class SyntheticAdapterAcceptanceResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter: str
    adapter_version: str
    destination_policy_sha256: str
    form_pattern: str
    form_fingerprint: str
    form_payload_sha256: str


@dataclass
class _SyntheticLocator:
    count_value: int = 1
    attribute_value: str | None = None
    value: str = ""

    def count(self) -> int:
        return self.count_value

    def get_attribute(self, _name: str) -> str | None:
        return self.attribute_value

    def click(self, *, timeout: float) -> None:
        del timeout
        raise AssertionError("synthetic acceptance must never click")

    def fill(self, value: str) -> None:
        self.value = value

    def input_value(self) -> str:
        return self.value

    def set_input_files(self, files: str) -> None:
        self.value = files

    def text_content(self) -> str | None:
        return None


class _SyntheticGreenhousePage:
    """In-memory page shape that exercises the production adapter without network or click."""

    def __init__(self) -> None:
        self.url = "https://boards.greenhouse.io/careeros-synthetic/jobs/acceptance"
        form = _SyntheticLocator(attribute_value=f"{self.url}/submit")
        self._locators = {
            "form#application_form": form,
            "form#application_form #first_name": _SyntheticLocator(),
            "form#application_form #last_name": _SyntheticLocator(),
            "form#application_form #email": _SyntheticLocator(),
            "form#application_form input[type='file'][name='resume']": _SyntheticLocator(),
            "form#application_form #submit_app": _SyntheticLocator(),
        }
        self._absent = _SyntheticLocator(count_value=0)

    def locator(self, selector: str) -> _SyntheticLocator:
        return self._locators.get(selector, self._absent)

    def wait_for_load_state(self, state: str, *, timeout: float) -> None:
        del state, timeout

    def screenshot(self, *, type: str, full_page: bool) -> bytes:
        del type, full_page
        raise AssertionError("synthetic acceptance does not capture click evidence")

    def content(self) -> str:
        return "<form id='application_form'>synthetic acceptance</form>"


class SyntheticGreenhouseAcceptanceRunner:
    """Exercise inspect/populate/recheck for the exact controlled adapter, never execute it."""

    def run(self, payload: ControlledGreenhouseFormPayload) -> SyntheticAdapterAcceptanceResult:
        adapter = GreenhouseControlledAdapter(enabled=False)
        page = _SyntheticGreenhousePage()
        before = adapter.inspect(page, page.url)
        adapter.populate(page, payload)
        adapter.verify_populated(page, payload)
        after = adapter.inspect(page, page.url)
        if before != after:
            raise ValueError("synthetic Greenhouse form identity changed during acceptance")
        return SyntheticAdapterAcceptanceResult(
            adapter="greenhouse",
            adapter_version=adapter.VERSION,
            destination_policy_sha256=adapter.destination_policy_sha256,
            form_pattern=adapter.FORM_PATTERN,
            form_fingerprint=before.form_fingerprint,
            form_payload_sha256=payload.sha256(),
        )
