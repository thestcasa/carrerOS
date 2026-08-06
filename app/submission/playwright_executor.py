from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, Page, Route, WebSocketRoute, sync_playwright
from playwright.sync_api import Playwright as SyncPlaywright

from app.browser.paths import CandidatePathError, CandidateSessionPaths
from app.submission.contracts import (
    ControlledSubmissionError,
    ControlledSubmissionPreparationRequest,
    ControlledSubmissionRequest,
    ControlledSubmissionResult,
    PreparedControlledSubmission,
)
from app.submission.greenhouse import GreenhouseControlledAdapter, SubmissionPage
from app.submission_gate import FinalClickPermit


class GreenhousePlaywrightExecutor:
    """One-task executor that reopens an isolated profile and dispatches one final POST."""

    def __init__(self, runtime_root: Path, *, enabled: bool = False) -> None:
        self._paths = CandidateSessionPaths(runtime_root)
        self._adapter = GreenhouseControlledAdapter(enabled=enabled)
        self._playwright: SyncPlaywright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._target_url: str | None = None
        self._form_action: str | None = None
        self._click_post_remaining = 0

    def prepare(
        self, request: ControlledSubmissionPreparationRequest
    ) -> PreparedControlledSubmission:
        if self._context is not None:
            raise ControlledSubmissionError("controlled executor already owns a browser context")
        target_url = self._adapter.validate_target(request.target_url)
        try:
            session_directory = self._paths.session_directory(
                request.candidate_id, request.browser_session_id
            )
        except CandidatePathError as exc:
            raise ControlledSubmissionError(str(exc)) from exc
        profile_directory = session_directory / "playwright-profile"
        self._validate_profile(session_directory, profile_directory)
        self._playwright = sync_playwright().start()
        try:
            self._context = self._playwright.chromium.launch_persistent_context(
                str(profile_directory), headless=True, service_workers="block"
            )
            self._context.set_default_timeout(15_000)
            self._context.set_default_navigation_timeout(15_000)
            self._target_url = target_url
            self._context.route("**/*", self._route)
            self._context.route_web_socket("**/*", self._block_web_socket)
            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
            self._page.goto(target_url, wait_until="domcontentloaded")
            inspection = self._adapter.inspect(cast(SubmissionPage, self._page), target_url)
            self._validate_resume(
                request.candidate_id, request.form.resume_path, request.form.resume_sha256
            )
            self._adapter.populate(cast(SubmissionPage, self._page), request.form)
            populated_inspection = self._adapter.inspect(
                cast(SubmissionPage, self._page), target_url
            )
            if populated_inspection != inspection:
                raise ControlledSubmissionError(
                    "Greenhouse form fingerprint changed while it was populated"
                )
            self._form_action = inspection.form_action
            return PreparedControlledSubmission(
                attempt_id=request.attempt_id,
                inspection=inspection,
                form_payload_sha256=request.form.sha256(),
                pre_click_screenshot_png=self._page.screenshot(type="png", full_page=True),
                pre_click_page_html=self._page.content().encode(),
            )
        except Exception:
            self.abort()
            raise

    def execute(
        self,
        request: ControlledSubmissionRequest,
        permit: FinalClickPermit,
    ) -> ControlledSubmissionResult:
        if (
            self._page is None
            or self._target_url != request.target_url
            or self._form_action is None
        ):
            raise ControlledSubmissionError("controlled executor has no matching prepared page")
        self._validate_resume(
            request.candidate_id, request.form.resume_path, request.form.resume_sha256
        )
        try:
            return self._adapter.execute(
                cast(SubmissionPage, self._page),
                request,
                permit,
                authorize_single_post=self._authorize_single_post,
            )
        finally:
            self.abort()

    def abort(self) -> None:
        context, playwright = self._context, self._playwright
        self._context = None
        self._playwright = None
        self._page = None
        self._target_url = None
        self._form_action = None
        self._click_post_remaining = 0
        if context is not None:
            context.close()
        if playwright is not None:
            playwright.stop()

    def _route(self, route: Route) -> None:
        request = route.request
        target_url = self._target_url
        form_action = self._form_action
        if target_url is None:
            route.abort("blockedbyclient")
            return
        target = urlsplit(target_url)
        requested = urlsplit(request.url)
        same_origin = (
            requested.scheme == target.scheme
            and requested.hostname == target.hostname
            and requested.port == target.port
        )
        if request.method == "GET" and same_origin:
            route.continue_()
            return
        if (
            request.method == "POST"
            and form_action is not None
            and request.url == form_action
            and self._click_post_remaining == 1
        ):
            self._click_post_remaining = 0
            route.continue_()
            return
        route.abort("blockedbyclient")

    def _authorize_single_post(self) -> None:
        if self._click_post_remaining != 0:
            raise ControlledSubmissionError("controlled POST capability is already armed")
        self._click_post_remaining = 1

    @staticmethod
    def _block_web_socket(web_socket: WebSocketRoute) -> None:
        web_socket.close(code=1008, reason="controlled submission WebSockets are disabled")

    def _validate_profile(self, session_directory: Path, profile_directory: Path) -> None:
        expected_root = self._paths.root.resolve()
        expected_session = expected_root / session_directory.relative_to(self._paths.root)
        if (
            session_directory.is_symlink()
            or session_directory.resolve() != expected_session
            or not session_directory.is_dir()
            or profile_directory.is_symlink()
            or not profile_directory.is_dir()
            or profile_directory.resolve().parent != expected_session
        ):
            raise ControlledSubmissionError("candidate browser profile is missing or unsafe")

    def _validate_resume(self, candidate_id: str, resume_path: Path, expected_sha256: str) -> None:
        try:
            allowed_root = self._paths.allowed_artifact_root(candidate_id).resolve()
        except CandidatePathError as exc:
            raise ControlledSubmissionError(str(exc)) from exc
        raw_path = resume_path.absolute()
        if raw_path.is_symlink() or any(
            parent.is_symlink()
            for parent in raw_path.parents
            if parent != allowed_root and parent.is_relative_to(allowed_root)
        ):
            raise ControlledSubmissionError("reviewed resume path contains a symlink")
        try:
            resolved = raw_path.resolve(strict=True)
        except OSError as exc:
            raise ControlledSubmissionError("reviewed resume is missing") from exc
        if not resolved.is_relative_to(allowed_root) or not resolved.is_file():
            raise ControlledSubmissionError("reviewed resume escaped the candidate archive")
        if hashlib.sha256(resolved.read_bytes()).hexdigest() != expected_sha256:
            raise ControlledSubmissionError("reviewed resume content changed")
