from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from app.browser.contracts import (
    DryRunRequest,
    DryRunResult,
    FieldKind,
    FinalPageSnapshot,
    HumanActionReason,
    HumanActionResult,
    MappedField,
    UploadArtifact,
)
from app.browser.paths import CandidatePathError, CandidateSessionPaths


class BrowserDryRunError(ValueError):
    pass


_LABEL_KEYS = {
    "first name": "first_name",
    "given name": "first_name",
    "last name": "last_name",
    "family name": "last_name",
    "email": "email",
    "email address": "email",
    "phone": "phone",
    "phone number": "phone",
    "linkedin": "linkedin_url",
    "linkedin url": "linkedin_url",
    "github": "github_url",
    "cover letter": "cover_letter",
    "resume": "cv",
    "cv": "cv",
}

_PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63606060f80f0001040100c89f17d90000000049454e44ae426082"
)


def _normalized_label(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", label.casefold()).strip()


class SyntheticBrowserDryRunner:
    """Fill an in-memory synthetic form and stop before final submission.

    There is intentionally no click or submit method in this boundary.
    """

    def __init__(self, runtime_root: Path) -> None:
        self._paths = CandidateSessionPaths(runtime_root)

    def run(self, request: DryRunRequest) -> DryRunResult:
        try:
            session_directory = self._paths.session_directory(
                request.candidate_id, request.session_id
            )
        except CandidatePathError as exc:
            raise BrowserDryRunError(str(exc)) from exc
        mapped: list[MappedField] = []
        human_actions: list[HumanActionResult] = []
        upload_hashes: list[str] = []
        uploads = {upload.field_key: upload for upload in request.uploads}

        for field in request.form.fields:
            if field.kind == FieldKind.SUBMIT:
                continue
            if field.kind in {FieldKind.CAPTCHA, FieldKind.OTP}:
                reason = HumanActionReason(field.kind.value)
                human_actions.append(
                    HumanActionResult(
                        reason=reason,
                        field_id=field.field_id,
                        message=(
                            f"{field.kind.value.upper()} requires human completion in this session."
                        ),
                    )
                )
                continue
            key = _LABEL_KEYS.get(_normalized_label(field.label), field.field_id)
            if field.kind == FieldKind.FILE:
                artifact = uploads.get(key)
                if artifact is None:
                    if field.required:
                        human_actions.append(self._novel_action(field.field_id, field.label))
                    continue
                self._validate_upload(request, artifact)
                mapped.append(
                    MappedField(
                        field_id=field.field_id,
                        field_key=key,
                        kind=field.kind,
                        value=artifact.path.name,
                    )
                )
                upload_hashes.append(artifact.sha256)
                continue
            value = request.answers.get(key)
            if value is None:
                if field.required:
                    human_actions.append(self._novel_action(field.field_id, field.label))
                continue
            if field.kind == FieldKind.SELECT and str(value) not in field.options:
                raise BrowserDryRunError(f"answer for {field.field_id} is not an allowed option")
            mapped.append(
                MappedField(field_id=field.field_id, field_key=key, kind=field.kind, value=value)
            )

        submit_present = any(field.kind == FieldKind.SUBMIT for field in request.form.fields)
        final_page = FinalPageSnapshot(
            source_url=request.form.source_url,
            values=tuple(mapped),
            upload_hashes=tuple(upload_hashes),
            final_submit_present=submit_present,
        )
        session_directory.mkdir(parents=True, exist_ok=True)
        screenshot_path = session_directory / "final-page.png"
        snapshot_path = session_directory / "final-page.json"
        try:
            validated_session = self._paths.session_directory(
                request.candidate_id, request.session_id
            )
        except CandidatePathError as exc:
            raise BrowserDryRunError(str(exc)) from exc
        if validated_session != session_directory or any(
            path.is_symlink() for path in (screenshot_path, snapshot_path)
        ):
            raise BrowserDryRunError("browser output path contains a symlink")
        screenshot_path.write_bytes(_PNG_1PX)
        snapshot_path.write_text(
            json.dumps(final_page.model_dump(mode="json"), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return DryRunResult(
            application_id=request.application_id,
            candidate_id=request.candidate_id,
            session_id=request.session_id,
            session_directory=session_directory,
            screenshot_path=screenshot_path,
            final_page_snapshot_path=snapshot_path,
            mapped_fields=tuple(mapped),
            human_actions=tuple(human_actions),
            final_page=final_page,
            ready_for_human_review=not human_actions,
        )

    def _validate_upload(self, request: DryRunRequest, artifact: UploadArtifact) -> None:
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
        actual_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if actual_sha256 != artifact.sha256:
            raise BrowserDryRunError("upload content does not match its allowlisted hash")

    @staticmethod
    def _novel_action(field_id: str, label: str) -> HumanActionResult:
        return HumanActionResult(
            reason=HumanActionReason.NOVEL_REQUIRED_FIELD,
            field_id=field_id,
            message=f"Required field needs an approved answer: {label}",
        )
