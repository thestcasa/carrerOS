from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen
from uuid import uuid4

import pytest
from playwright.sync_api import Error as PlaywrightError
from pydantic import ValidationError

from app.browser import (
    BrowserFailureCategory,
    BrowserWorkerFailure,
    PlaywrightDryRunRequest,
    RestrictedPlaywrightWorker,
    UploadArtifact,
)
from app.browser.fixture_server import SyntheticATSHandler


@pytest.fixture
def synthetic_ats_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), SyntheticATSHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/application"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_playwright_fixture_pauses_and_resumes_same_persistent_profile(
    tmp_path: Path, synthetic_ats_url: str
) -> None:
    runtime_root = tmp_path / "runtime"
    candidate_id = "example_candidate"
    artifact_directory = (
        runtime_root / "candidates" / candidate_id / "application_archive" / "fixture"
    )
    artifact_directory.mkdir(parents=True)
    cv_path = artifact_directory / "fictional-cv.pdf"
    cv_path.write_bytes(b"%PDF-1.4\n% fictional browser fixture\n")
    cv_hash = hashlib.sha256(cv_path.read_bytes()).hexdigest()
    session_id = uuid4()
    request = PlaywrightDryRunRequest(
        application_id=uuid4(),
        candidate_id=candidate_id,
        session_id=session_id,
        fixture_url=synthetic_ats_url,
        answers={"first_name": "Morgan", "email": "morgan@example.invalid"},
        uploads=(UploadArtifact(field_key="cv", path=cv_path, sha256=cv_hash),),
        allowed_upload_sha256=frozenset({cv_hash}),
    )
    worker = RestrictedPlaywrightWorker(runtime_root, frozenset({synthetic_ats_url}))

    try:
        paused = worker.run(request)
    except BrowserWorkerFailure as exc:
        cause = exc.__cause__
        unavailable_markers = (
            "Executable doesn't exist",
            "error while loading shared libraries",
        )
        if (
            exc.category is BrowserFailureCategory.BROWSER_CRASH
            and isinstance(cause, PlaywrightError)
            and any(marker in str(cause) for marker in unavailable_markers)
        ):
            pytest.skip(f"Playwright Chromium runtime unavailable: {cause}")
        raise

    assert paused.human_action == "captcha"
    assert not paused.ready_for_human_review
    assert paused.final_submit_present
    assert paused.final_submit_clicked is False
    assert paused.allowed_network_requests == 1
    assert paused.blocked_network_requests >= 2
    assert paused.screenshot_path.is_file()
    assert paused.persistent_profile_directory.is_dir()
    assert paused.recovered_profile is False
    assert paused.upload_hashes == (cv_hash,)

    worker.acknowledge_fixture_human_action(
        candidate_id=candidate_id,
        session_id=session_id,
        fixture_url=synthetic_ats_url,
        synthetic_fixture_acknowledged=True,
    )
    resumed = worker.run(request)

    assert resumed.human_action is None
    assert resumed.ready_for_human_review
    assert resumed.persistent_profile_directory == paused.persistent_profile_directory
    assert resumed.recovered_profile is True
    assert resumed.final_submit_clicked is False
    snapshot = resumed.final_page_snapshot_path.read_text(encoding="utf-8")
    assert "<main>" in snapshot
    assert '<label for="first-name">First name</label>' in snapshot


def test_playwright_contract_rejects_external_navigation() -> None:
    with pytest.raises(ValidationError, match="fixture_url"):
        PlaywrightDryRunRequest(
            application_id=uuid4(),
            candidate_id="example_candidate",
            session_id=uuid4(),
            fixture_url="https://jobs.example.invalid/application",
            answers={},
        )


def test_fixture_exposes_only_exact_allowlisted_challenge_variants(
    synthetic_ats_url: str,
) -> None:
    with urlopen(f"{synthetic_ats_url}?challenge=none", timeout=2) as response:
        no_challenge = response.read().decode()
    with urlopen(f"{synthetic_ats_url}?challenge=otp", timeout=2) as response:
        otp = response.read().decode()

    assert "data-human-action" not in no_challenge
    assert 'data-human-action="otp"' in otp
    with pytest.raises(HTTPError) as caught:
        urlopen(f"{synthetic_ats_url}?challenge=unknown", timeout=2)
    assert caught.value.code == 404


def test_playwright_worker_rejects_unapproved_loopback_origin(tmp_path: Path) -> None:
    worker = RestrictedPlaywrightWorker(tmp_path / "runtime", frozenset({"http://127.0.0.1:8090"}))
    request = PlaywrightDryRunRequest(
        application_id=uuid4(),
        candidate_id="example_candidate",
        session_id=uuid4(),
        fixture_url="http://127.0.0.1:9090/application",
        answers={},
    )

    with pytest.raises(BrowserWorkerFailure) as caught:
        worker.run(request)
    assert caught.value.category is BrowserFailureCategory.VALIDATION_FAILURE


def test_playwright_worker_rejects_symlinked_session_directory(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    session_id = uuid4()
    sessions_root = runtime_root / "candidates" / "example_candidate" / "sessions"
    sessions_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (sessions_root / str(session_id)).symlink_to(outside, target_is_directory=True)
    fixture_url = "http://127.0.0.1:8090/application"
    worker = RestrictedPlaywrightWorker(runtime_root, frozenset({fixture_url}))
    request = PlaywrightDryRunRequest(
        application_id=uuid4(),
        candidate_id="example_candidate",
        session_id=session_id,
        fixture_url=fixture_url,
        answers={},
    )

    with pytest.raises(BrowserWorkerFailure) as caught:
        worker.run(request)
    assert caught.value.category is BrowserFailureCategory.VALIDATION_FAILURE


def test_playwright_worker_rejects_symlinked_profile_directory(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    session_id = uuid4()
    session_root = runtime_root / "candidates" / "example_candidate" / "sessions" / str(session_id)
    session_root.mkdir(parents=True)
    outside = tmp_path / "outside-profile"
    outside.mkdir()
    (session_root / "playwright-profile").symlink_to(outside, target_is_directory=True)
    fixture_url = "http://127.0.0.1:8090/application"
    worker = RestrictedPlaywrightWorker(runtime_root, frozenset({fixture_url}))
    request = PlaywrightDryRunRequest(
        application_id=uuid4(),
        candidate_id="example_candidate",
        session_id=session_id,
        fixture_url=fixture_url,
        answers={},
    )

    with pytest.raises(BrowserWorkerFailure) as caught:
        worker.run(request)
    assert caught.value.category is BrowserFailureCategory.VALIDATION_FAILURE
