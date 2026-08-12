from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.browser.contracts import PlaywrightDryRunResult

_MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024
_MAX_HTML_BYTES = 5 * 1024 * 1024


class BrowserEvidenceError(ValueError):
    pass


class BrowserAttemptManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    task_id: UUID
    attempt: int = Field(ge=1)
    candidate_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    application_id: UUID
    session_id: UUID
    started_at: datetime
    completed_at: datetime
    recovered_profile: bool
    fixture_url: str
    mapped_field_keys: tuple[str, ...]
    upload_hashes: tuple[str, ...]
    final_submit_present: bool
    final_submit_clicked: bool
    allowed_network_requests: int = Field(ge=0)
    blocked_network_requests: int = Field(ge=0)
    screenshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    final_page_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class StoredBrowserEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    directory: Path
    screenshot_path: Path
    final_page_path: Path
    manifest_path: Path
    manifest: BrowserAttemptManifest


class BrowserEvidenceStore:
    """Append-only browser evidence publisher scoped to one task attempt."""

    def __init__(self, runtime_root: Path) -> None:
        self._runtime_root = runtime_root.resolve()

    def store(
        self,
        *,
        task_id: UUID,
        attempt: int,
        result: PlaywrightDryRunResult,
        started_at: datetime,
        completed_at: datetime,
    ) -> StoredBrowserEvidence:
        if attempt < 1 or not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", result.candidate_id):
            raise BrowserEvidenceError("browser evidence identity is invalid")
        if completed_at < started_at:
            raise BrowserEvidenceError("browser evidence timestamps are invalid")
        expected_session = (
            self._runtime_root
            / "candidates"
            / result.candidate_id
            / "sessions"
            / str(result.session_id)
        )
        if result.session_directory.absolute() != expected_session:
            raise BrowserEvidenceError("browser evidence session identity does not match")
        expected_screenshot = expected_session / "playwright-final-page.png"
        expected_final_page = expected_session / "playwright-final-page.html"
        if (
            result.screenshot_path.absolute() != expected_screenshot
            or result.final_page_snapshot_path.absolute() != expected_final_page
        ):
            raise BrowserEvidenceError("browser evidence source escaped its session")
        screenshot = self._read_session_file(
            expected_session, expected_screenshot.name, _MAX_SCREENSHOT_BYTES
        )
        final_page = self._read_session_file(
            expected_session, expected_final_page.name, _MAX_HTML_BYTES
        )
        if not screenshot.startswith(b"\x89PNG\r\n\x1a\n"):
            raise BrowserEvidenceError("browser screenshot is not a PNG")
        try:
            final_page.decode("utf-8")
        except UnicodeError as exc:
            raise BrowserEvidenceError("browser final page is not UTF-8") from exc

        manifest = BrowserAttemptManifest(
            task_id=task_id,
            attempt=attempt,
            candidate_id=result.candidate_id,
            application_id=result.application_id,
            session_id=result.session_id,
            started_at=started_at,
            completed_at=completed_at,
            recovered_profile=result.recovered_profile,
            fixture_url=result.fixture_url,
            mapped_field_keys=tuple(sorted(result.mapped_values)),
            upload_hashes=result.upload_hashes,
            final_submit_present=result.final_submit_present,
            final_submit_clicked=result.final_submit_clicked,
            allowed_network_requests=result.allowed_network_requests,
            blocked_network_requests=result.blocked_network_requests,
            screenshot_sha256=hashlib.sha256(screenshot).hexdigest(),
            final_page_sha256=hashlib.sha256(final_page).hexdigest(),
        )
        candidate_root = self._runtime_root / "candidates" / result.candidate_id
        evidence_root = candidate_root / "browser_evidence" / str(task_id)
        destination = evidence_root / f"attempt-{attempt}"
        self._prepare_roots(candidate_root, evidence_root)
        if destination.exists() or destination.is_symlink():
            stored = self.load(destination)
            if stored.manifest != manifest:
                raise BrowserEvidenceError("browser evidence attempt already exists with drift")
            return stored

        staging = evidence_root / f".attempt-{attempt}.{uuid4().hex}.tmp"
        try:
            staging.mkdir(mode=0o700)
            (staging / "pre-submit.png").write_bytes(screenshot)
            (staging / "final-page.html").write_bytes(final_page)
            (staging / "manifest.json").write_text(
                json.dumps(
                    manifest.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            for path in staging.iterdir():
                path.chmod(0o600)
            os.replace(staging, destination)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return self.load(destination)

    def discard(self, evidence: StoredBrowserEvidence) -> None:
        """Remove an unreferenced attempt after its task lease is proven stale."""

        manifest = evidence.manifest
        expected = (
            self._runtime_root
            / "candidates"
            / manifest.candidate_id
            / "browser_evidence"
            / str(manifest.task_id)
            / f"attempt-{manifest.attempt}"
        )
        if evidence.directory.absolute() != expected or evidence.directory.is_symlink():
            raise BrowserEvidenceError("browser evidence discard path is unsafe")
        loaded = self.load(evidence.directory)
        if loaded.manifest != manifest:
            raise BrowserEvidenceError("browser evidence discard identity does not match")
        quarantine = expected.parent / f".discard-{expected.name}.{uuid4().hex}.tmp"
        os.replace(expected, quarantine)
        shutil.rmtree(quarantine)

    def load(self, directory: Path) -> StoredBrowserEvidence:
        if directory.is_symlink() or not directory.is_dir():
            raise BrowserEvidenceError("browser evidence directory is unsafe")
        paths = tuple(directory.iterdir())
        if {path.name for path in paths} != {
            "pre-submit.png",
            "final-page.html",
            "manifest.json",
        }:
            raise BrowserEvidenceError("browser evidence attempt is incomplete")
        for path in paths:
            metadata = path.lstat()
            if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise BrowserEvidenceError("browser evidence file is unsafe")
        screenshot_path = directory / "pre-submit.png"
        final_page_path = directory / "final-page.html"
        manifest_path = directory / "manifest.json"
        try:
            manifest = BrowserAttemptManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise BrowserEvidenceError("browser evidence manifest is invalid") from exc
        screenshot = self._read_regular(screenshot_path, _MAX_SCREENSHOT_BYTES)
        final_page = self._read_regular(final_page_path, _MAX_HTML_BYTES)
        if (
            hashlib.sha256(screenshot).hexdigest() != manifest.screenshot_sha256
            or hashlib.sha256(final_page).hexdigest() != manifest.final_page_sha256
        ):
            raise BrowserEvidenceError("browser evidence hash does not match")
        return StoredBrowserEvidence(
            directory=directory,
            screenshot_path=screenshot_path,
            final_page_path=final_page_path,
            manifest_path=manifest_path,
            manifest=manifest,
        )

    @staticmethod
    def _read_regular(path: Path, maximum_bytes: int) -> bytes:
        if path.is_symlink() or not path.is_file():
            raise BrowserEvidenceError("browser evidence source is unsafe")
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size > maximum_bytes
        ):
            raise BrowserEvidenceError("browser evidence source exceeds safe limits")
        return path.read_bytes()

    @staticmethod
    def _read_session_file(directory: Path, filename: str, maximum_bytes: int) -> bytes:
        try:
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise BrowserEvidenceError("browser evidence session is unsafe") from exc
        try:
            try:
                file_fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
            except OSError as exc:
                raise BrowserEvidenceError("browser evidence source is unsafe") from exc
            try:
                before = os.fstat(file_fd)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_nlink != 1
                    or before.st_size > maximum_bytes
                ):
                    raise BrowserEvidenceError("browser evidence source exceeds safe limits")
                chunks: list[bytes] = []
                remaining = maximum_bytes + 1
                while remaining:
                    chunk = os.read(file_fd, min(64 * 1024, remaining))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                content = b"".join(chunks)
                after = os.fstat(file_fd)
                if len(content) > maximum_bytes or (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                ) != (after.st_dev, after.st_ino, after.st_size):
                    raise BrowserEvidenceError("browser evidence source changed while reading")
                return content
            finally:
                os.close(file_fd)
        finally:
            os.close(directory_fd)

    def _prepare_roots(self, candidate_root: Path, evidence_root: Path) -> None:
        candidates_root = self._runtime_root / "candidates"
        task_root = evidence_root.parent
        for path, parent in (
            (candidates_root, self._runtime_root),
            (candidate_root, candidates_root),
            (task_root, candidate_root),
            (evidence_root, task_root),
        ):
            if path.is_symlink():
                raise BrowserEvidenceError("browser evidence root contains a symlink")
            path.mkdir(mode=0o700, exist_ok=True)
            if not path.is_dir() or path.resolve().parent != parent.resolve():
                raise BrowserEvidenceError("browser evidence root is unsafe")
