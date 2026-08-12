from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from app.browser.contracts import PlaywrightDryRunRequest, PlaywrightDryRunResult
from app.browser.paths import CandidateSessionPaths

_PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63606060f80f0001040100c89f17d90000000049454e44ae426082"
)


class DeterministicBrowserExecutor:
    """Offline browser executor for deterministic tests; it has no submit operation."""

    def __init__(self, runtime_root: Path) -> None:
        self._paths = CandidateSessionPaths(runtime_root)

    def run(self, request: PlaywrightDryRunRequest) -> PlaywrightDryRunResult:
        session_directory = self._paths.session_directory(request.candidate_id, request.session_id)
        recovered_profile = (session_directory / "playwright-profile").is_dir()
        session_directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        profile = session_directory / "playwright-profile"
        profile.mkdir(mode=0o700, exist_ok=True)
        screenshot = session_directory / "playwright-final-page.png"
        snapshot = session_directory / "playwright-final-page.html"
        screenshot.write_bytes(_PNG_1PX)
        snapshot.write_text(
            "<!doctype html><html><body><main>Fictional pre-submit page</main></body></html>\n",
            encoding="utf-8",
        )
        challenge = parse_qs(urlsplit(request.fixture_url).query).get("challenge", ["none"])[0]
        human_action: Literal["captcha", "otp"] | None
        if challenge == "captcha":
            human_action = "captcha"
        elif challenge == "otp":
            human_action = "otp"
        else:
            human_action = None
        return PlaywrightDryRunResult(
            application_id=request.application_id,
            candidate_id=request.candidate_id,
            session_id=request.session_id,
            fixture_url=request.fixture_url,
            session_directory=session_directory,
            persistent_profile_directory=profile,
            recovered_profile=recovered_profile,
            screenshot_path=screenshot,
            final_page_snapshot_path=snapshot,
            mapped_values={
                **request.answers,
                **{upload.field_key: upload.path.name for upload in request.uploads},
            },
            upload_hashes=tuple(upload.sha256 for upload in request.uploads),
            human_action=human_action,
            final_submit_present=True,
            allowed_network_requests=1,
            blocked_network_requests=2,
            ready_for_human_review=human_action is None,
        )
