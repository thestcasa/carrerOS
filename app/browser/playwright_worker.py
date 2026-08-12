from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from playwright.sync_api import (
    BrowserContext,
    Page,
    Route,
    WebSocketRoute,
    sync_playwright,
)
from playwright.sync_api import (
    Error as PlaywrightError,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from app.browser.contracts import (
    BrowserFailureCategory,
    BrowserWorkerFailure,
    PlaywrightDryRunRequest,
    PlaywrightDryRunResult,
    UploadArtifact,
)
from app.browser.dry_run import BrowserDryRunError
from app.browser.paths import CandidatePathError, CandidateSessionPaths


class RestrictedPlaywrightWorker:
    """Runs Chromium only against a loopback synthetic ATS and never clicks submit."""

    def __init__(self, runtime_root: Path, allowed_fixture_urls: frozenset[str]) -> None:
        self._paths = CandidateSessionPaths(runtime_root)
        if not allowed_fixture_urls:
            raise BrowserDryRunError("at least one synthetic fixture URL must be allowlisted")
        for url in allowed_fixture_urls:
            self._fixture_origin(url)
        self._allowed_fixture_urls = allowed_fixture_urls

    def run(self, request: PlaywrightDryRunRequest) -> PlaywrightDryRunResult:
        try:
            return self._run(request)
        except BrowserWorkerFailure:
            raise
        except PlaywrightTimeoutError as exc:
            raise BrowserWorkerFailure(
                BrowserFailureCategory.TIMEOUT,
                retryable=True,
                safe_details="The synthetic browser action exceeded its bounded timeout.",
            ) from exc
        except PlaywrightError as exc:
            raise BrowserWorkerFailure(
                BrowserFailureCategory.BROWSER_CRASH,
                retryable=True,
                safe_details="The isolated browser process stopped unexpectedly.",
            ) from exc
        except BrowserDryRunError as exc:
            raise BrowserWorkerFailure(
                BrowserFailureCategory.VALIDATION_FAILURE,
                retryable=False,
                safe_details="The synthetic browser package failed validation.",
            ) from exc

    def _run(self, request: PlaywrightDryRunRequest) -> PlaywrightDryRunResult:
        self._require_allowed_fixture(request.fixture_url)
        try:
            session_directory = self._paths.session_directory(
                request.candidate_id, request.session_id
            )
        except CandidatePathError as exc:
            raise BrowserDryRunError(str(exc)) from exc
        self._validate_session_path(session_directory)
        profile_directory = session_directory / "playwright-profile"
        recovered_profile = profile_directory.is_dir()
        if profile_directory.is_symlink():
            raise BrowserDryRunError("candidate browser profile path contains a symlink")
        session_directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        session_directory.chmod(0o700)
        self._validate_session_path(session_directory)
        mapped_values: dict[str, str | bool] = {}
        upload_hashes: list[str] = []

        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(profile_directory), headless=True, service_workers="block"
            )
            try:
                context.set_default_timeout(15_000)
                context.set_default_navigation_timeout(15_000)
                network_audit = self._restrict_context(context, request.fixture_url)
                page = context.pages[0] if context.pages else context.new_page()
                self._navigate(page, request.fixture_url)
                if page.url != request.fixture_url:
                    raise BrowserDryRunError(
                        "Playwright navigation left the allowlisted fixture URL"
                    )
                closed = page.locator("[data-job-closed]")
                if closed.count() and closed.first.is_visible():
                    raise BrowserWorkerFailure(
                        BrowserFailureCategory.CLOSED_JOB,
                        retryable=False,
                        safe_details="The synthetic opening is closed.",
                    )
                self._complete_visible_steps(
                    page,
                    request,
                    mapped_values,
                    upload_hashes,
                )

                human_action = self._human_action(page)
                if human_action is None and self._has_unmapped_required_field(page, mapped_values):
                    human_action = "novel_required_field"
                submit = page.locator("[data-final-submit]")
                submit_present = submit.count() > 0 and submit.first.is_visible()
                screenshot_path = session_directory / "playwright-final-page.png"
                snapshot_path = session_directory / "playwright-final-page.html"
                metadata_path = session_directory / "playwright-session.json"
                if any(
                    path.is_symlink()
                    for path in (profile_directory, screenshot_path, snapshot_path, metadata_path)
                ):
                    raise BrowserDryRunError("candidate browser output path contains a symlink")
                page.screenshot(path=str(screenshot_path), full_page=True)
                snapshot_path.write_text(page.content(), encoding="utf-8")
                metadata = {
                    "fixture_url": page.url,
                    "mapped_field_keys": sorted(mapped_values),
                    "upload_hashes": upload_hashes,
                    "human_action": human_action,
                    "final_submit_present": submit_present,
                    "final_submit_clicked": False,
                    "allowed_network_requests": network_audit["allowed"],
                    "blocked_network_requests": network_audit["blocked"],
                }
                metadata_path.write_text(
                    json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8"
                )
                for artifact_path in (screenshot_path, snapshot_path, metadata_path):
                    artifact_path.chmod(0o600)
            finally:
                context.close()
        profile_directory.chmod(0o700)
        if network_audit["allowed"] != 1:
            raise BrowserDryRunError("synthetic fixture navigation audit is invalid")

        return PlaywrightDryRunResult(
            application_id=request.application_id,
            candidate_id=request.candidate_id,
            session_id=request.session_id,
            fixture_url=request.fixture_url,
            session_directory=session_directory,
            persistent_profile_directory=profile_directory,
            recovered_profile=recovered_profile,
            screenshot_path=screenshot_path,
            final_page_snapshot_path=snapshot_path,
            mapped_values=mapped_values,
            upload_hashes=tuple(upload_hashes),
            human_action=human_action,
            final_submit_present=submit_present,
            allowed_network_requests=network_audit["allowed"],
            blocked_network_requests=network_audit["blocked"],
            ready_for_human_review=human_action is None,
        )

    def acknowledge_fixture_human_action(
        self,
        *,
        candidate_id: str,
        session_id: UUID,
        fixture_url: str,
        synthetic_fixture_acknowledged: bool,
    ) -> None:
        """Record explicit human completion in the same synthetic persistent profile."""
        if not synthetic_fixture_acknowledged:
            raise BrowserDryRunError("synthetic fixture acknowledgement is required")
        self._require_allowed_fixture(fixture_url)
        try:
            session_directory = self._paths.session_directory(candidate_id, session_id)
        except CandidatePathError as exc:
            raise BrowserDryRunError(str(exc)) from exc
        self._validate_session_path(session_directory)
        profile_directory = session_directory / "playwright-profile"
        if (
            profile_directory.is_symlink()
            or not profile_directory.is_dir()
            or profile_directory.resolve() != profile_directory
        ):
            raise BrowserDryRunError("persistent browser profile is missing")
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(profile_directory), headless=True, service_workers="block"
            )
            try:
                network_audit = self._restrict_context(context, fixture_url)
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(fixture_url, wait_until="domcontentloaded")
                if page.url != fixture_url:
                    raise BrowserDryRunError(
                        "Playwright navigation left the allowlisted fixture URL"
                    )
                page.evaluate("localStorage.setItem('syntheticHumanActionCompleted', 'true')")
                if network_audit["allowed"] != 1:
                    raise BrowserDryRunError("synthetic fixture navigation audit is invalid")
            finally:
                context.close()

    @staticmethod
    def _fill_available_answers(
        page: Page, answers: dict[str, str | bool], mapped_values: dict[str, str | bool]
    ) -> None:
        for field_key, value in answers.items():
            if field_key in mapped_values:
                continue
            locator = page.locator(f'[data-field-key="{field_key}"]')
            if locator.count() != 1 or not locator.first.is_visible():
                continue
            field_type = locator.get_attribute("type")
            tag_name = locator.evaluate("element => element.tagName.toLowerCase()")
            if field_type == "checkbox":
                locator.set_checked(bool(value))
                mapped_values[field_key] = locator.is_checked()
            elif tag_name == "select":
                locator.select_option(str(value))
                mapped_values[field_key] = locator.input_value()
            else:
                locator.fill(str(value))
                mapped_values[field_key] = locator.input_value()

    def _complete_visible_steps(
        self,
        page: Page,
        request: PlaywrightDryRunRequest,
        mapped_values: dict[str, str | bool],
        upload_hashes: list[str],
    ) -> None:
        for _step in range(4):
            self._fill_available_answers(page, request.answers, mapped_values)
            for upload in request.uploads:
                if upload.field_key in mapped_values:
                    continue
                locator = page.locator(f'[data-field-key="{upload.field_key}"]')
                if locator.count() != 1 or not locator.first.is_visible():
                    continue
                self._validate_upload(request, upload)
                locator.set_input_files(str(upload.path.resolve()))
                if not locator.input_value().endswith(upload.path.name):
                    raise BrowserDryRunError("synthetic fixture did not retain the selected upload")
                upload_hashes.append(upload.sha256)
                mapped_values[upload.field_key] = upload.path.name
            next_step = page.locator("[data-next-step]")
            if next_step.count() == 0 or not next_step.first.is_visible():
                break
            next_step.first.click()
        expected = set(request.answers) | {upload.field_key for upload in request.uploads}
        if set(mapped_values) != expected:
            raise BrowserWorkerFailure(
                BrowserFailureCategory.SELECTOR_FAILURE,
                retryable=True,
                safe_details="A required synthetic form field was unavailable.",
            )

    @staticmethod
    def _has_unmapped_required_field(page: Page, mapped_values: dict[str, str | bool]) -> bool:
        required = page.locator("[required][data-field-key]")
        for index in range(required.count()):
            field = required.nth(index)
            key = field.get_attribute("data-field-key")
            if field.is_visible() and key not in mapped_values:
                return True
        return False

    @staticmethod
    def _human_action(page: Page) -> str | None:
        for kind in ("captcha", "otp"):
            locator = page.locator(f'[data-human-action="{kind}"]')
            if locator.count() and locator.first.is_visible():
                return kind
        return None

    @staticmethod
    def _navigate(page: Page, fixture_url: str) -> None:
        try:
            page.goto(fixture_url, wait_until="domcontentloaded")
        except PlaywrightTimeoutError:
            raise
        except PlaywrightError as exc:
            raise BrowserWorkerFailure(
                BrowserFailureCategory.TRANSIENT_NETWORK,
                retryable=True,
                safe_details="The loopback synthetic fixture was temporarily unavailable.",
            ) from exc

    def _validate_upload(self, request: PlaywrightDryRunRequest, artifact: UploadArtifact) -> None:
        try:
            allowed_root = self._paths.allowed_artifact_root(request.candidate_id).resolve()
        except CandidatePathError as exc:
            raise BrowserDryRunError(str(exc)) from exc
        raw_path = artifact.path.absolute()
        if raw_path.is_symlink() or any(
            parent.is_symlink()
            for parent in raw_path.parents
            if parent != allowed_root and parent.is_relative_to(allowed_root)
        ):
            raise BrowserDryRunError("upload path contains a symlink")
        artifact_path = raw_path.resolve()
        if not artifact_path.is_relative_to(allowed_root):
            raise BrowserDryRunError("upload path is outside the candidate artifact allowlist")
        if artifact.sha256 not in request.allowed_upload_sha256:
            raise BrowserDryRunError("upload hash is not allowlisted")
        if not artifact_path.is_file():
            raise BrowserDryRunError("allowlisted upload does not exist")
        if hashlib.sha256(artifact_path.read_bytes()).hexdigest() != artifact.sha256:
            raise BrowserDryRunError("upload content does not match its allowlisted hash")

    @staticmethod
    def _fixture_origin(url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise BrowserDryRunError("Playwright navigation is restricted to loopback fixtures")
        try:
            port = parsed.port
        except ValueError as exc:
            raise BrowserDryRunError("synthetic fixture URL has an invalid port") from exc
        if parsed.username or parsed.password or port is None:
            raise BrowserDryRunError("synthetic fixture URL is invalid")
        return f"http://{parsed.hostname}:{port}"

    def _require_allowed_fixture(self, url: str) -> str:
        origin = self._fixture_origin(url)
        if url not in self._allowed_fixture_urls:
            raise BrowserDryRunError("synthetic fixture URL is not allowlisted")
        return origin

    @staticmethod
    def _restrict_context(context: BrowserContext, allowed_url: str) -> dict[str, int]:
        audit = {"allowed": 0, "blocked": 0}

        def handle_route(route: Route) -> None:
            request = route.request
            if (
                audit["allowed"] == 0
                and request.url == allowed_url
                and request.method == "GET"
                and request.resource_type == "document"
            ):
                audit["allowed"] += 1
                route.continue_()
            else:
                audit["blocked"] += 1
                route.abort("blockedbyclient")

        def block_web_socket(web_socket: WebSocketRoute) -> None:
            audit["blocked"] += 1
            web_socket.close(code=1008, reason="synthetic fixture network is disabled")

        context.route("**/*", handle_route)
        context.route_web_socket("**/*", block_web_socket)
        return audit

    def _validate_session_path(self, session_directory: Path) -> None:
        expected_root = self._paths.root.resolve()
        expected = expected_root / session_directory.relative_to(self._paths.root)
        if session_directory.resolve() != expected:
            raise BrowserDryRunError("candidate browser session path contains a symlink")
        if not expected.is_relative_to(expected_root):
            raise BrowserDryRunError("candidate browser session escaped the runtime root")
