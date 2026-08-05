from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.browser import (
    BrowserDryRunError,
    DryRunRequest,
    FieldKind,
    HumanActionReason,
    SyntheticBrowserDryRunner,
    UploadArtifact,
)
from app.browser.fixtures import standard_application_form


def _request(
    runtime_root: Path,
    *,
    candidate_id: str = "candidate_alpha",
    challenge: FieldKind | None = None,
) -> DryRunRequest:
    content = b"fictional CV fixture"
    digest = hashlib.sha256(content).hexdigest()
    cv_path = runtime_root / "candidates" / candidate_id / "application_archive" / "cv.pdf"
    cv_path.parent.mkdir(parents=True)
    cv_path.write_bytes(content)
    return DryRunRequest(
        application_id=uuid4(),
        candidate_id=candidate_id,
        session_id=uuid4(),
        form=standard_application_form(challenge=challenge),
        answers={"first_name": "Avery", "email": "avery@example.invalid"},
        uploads=(UploadArtifact(field_key="cv", path=cv_path, sha256=digest),),
        allowed_upload_sha256=frozenset({digest}),
    )


def test_dry_run_maps_fields_extracts_final_page_and_never_submits(tmp_path: Path) -> None:
    request = _request(tmp_path)
    result = SyntheticBrowserDryRunner(tmp_path).run(request)

    assert tuple(item.field_key for item in result.mapped_fields) == (
        "first_name",
        "email",
        "cv",
    )
    assert result.session_directory == (
        tmp_path / "candidates" / request.candidate_id / "sessions" / str(request.session_id)
    )
    assert result.final_page.final_submit_present
    assert result.final_page.final_submit_clicked is False
    assert result.screenshot_path.read_bytes().startswith(b"\x89PNG")
    assert result.final_page_snapshot_path.is_file()
    assert result.submitted is False
    assert result.ready_for_human_review


@pytest.mark.parametrize(
    ("challenge", "reason"),
    [
        (FieldKind.CAPTCHA, HumanActionReason.CAPTCHA),
        (FieldKind.OTP, HumanActionReason.OTP),
    ],
)
def test_challenge_creates_resumable_human_action_without_bypass(
    tmp_path: Path, challenge: FieldKind, reason: HumanActionReason
) -> None:
    result = SyntheticBrowserDryRunner(tmp_path).run(_request(tmp_path, challenge=challenge))

    assert len(result.human_actions) == 1
    assert result.human_actions[0].reason == reason
    assert result.human_actions[0].resumable
    assert not result.ready_for_human_review
    assert not result.submitted


def test_upload_must_be_candidate_scoped_hash_allowlisted_and_unchanged(tmp_path: Path) -> None:
    request = _request(tmp_path)
    other_path = tmp_path / "candidates" / "candidate_beta" / "application_archive" / "cv.pdf"
    other_path.parent.mkdir(parents=True)
    other_path.write_bytes(b"fictional CV fixture")
    wrong_candidate_upload = request.uploads[0].model_copy(update={"path": other_path})

    with pytest.raises(BrowserDryRunError, match="outside the candidate"):
        SyntheticBrowserDryRunner(tmp_path).run(
            request.model_copy(update={"uploads": (wrong_candidate_upload,)})
        )

    request.uploads[0].path.write_bytes(b"tampered")
    with pytest.raises(BrowserDryRunError, match="does not match"):
        SyntheticBrowserDryRunner(tmp_path).run(request)


def test_unknown_required_field_pauses_for_approved_answer(tmp_path: Path) -> None:
    request = _request(tmp_path)
    form = request.form.model_copy(
        update={
            "fields": (
                *request.form.fields[:-1],
                request.form.fields[0].model_copy(
                    update={"field_id": "novel", "label": "Security clearance"}
                ),
                request.form.fields[-1],
            )
        }
    )
    result = SyntheticBrowserDryRunner(tmp_path).run(request.model_copy(update={"form": form}))

    assert result.human_actions[-1].reason == HumanActionReason.NOVEL_REQUIRED_FIELD
    assert "Security clearance" in result.human_actions[-1].message
    assert not result.ready_for_human_review


def test_candidate_session_path_rejects_traversal(tmp_path: Path) -> None:
    request = _request(tmp_path)
    with pytest.raises(ValidationError):
        DryRunRequest.model_validate({**request.model_dump(), "candidate_id": "../candidate_beta"})
