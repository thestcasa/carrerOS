from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from app.candidates.cv_import import CVImportRequest, extract_cv_draft
from app.candidates.models import ClaimFact
from app.candidates.service import CandidateService, CandidateUpdateError

FICTIONAL_CV = """Fictional Candidate

EDUCATION
Example University | MSc | Computer Science | Exampleton | 2020-09 | 2022-06

EXPERIENCE
Fictional Robotics Ltd | ML Engineer | Exampleton | 2022-07 | present | Python, SQL
- Improved a fictional benchmark in a controlled test.
- Built a deterministic evaluation pipeline.
"""


def _request(text: str = FICTIONAL_CV) -> CVImportRequest:
    return CVImportRequest(
        filename="fictional-cv.txt",
        content_base64=base64.b64encode(text.encode()).decode(),
    )


def test_cv_import_persists_only_unapproved_extraction_and_applies_idempotently(
    copied_candidates_root: Path,
) -> None:
    service = CandidateService(copied_candidates_root)

    draft = service.create_cv_import("example_candidate", _request())

    assert draft.approval_required
    assert len(draft.education.items) == 1
    assert len(draft.experience.items) == 1
    imported_experience = draft.experience.items[0]
    assert not imported_experience.approved
    assert imported_experience.confidentiality == "restricted"
    assert all(
        isinstance(claim, ClaimFact) and not claim.approved
        for claim in imported_experience.achievements
    )
    stored_path = (
        copied_candidates_root / "example_candidate" / ".imports" / f"{draft.import_id}.json"
    )
    stored = json.loads(stored_path.read_text(encoding="utf-8"))
    assert "content_base64" not in stored
    assert stored_path.stat().st_mode & 0o777 == 0o600

    applied = service.apply_cv_import("example_candidate", draft.import_id)
    replayed = service.apply_cv_import("example_candidate", draft.import_id)

    assert applied.profile_version == "1.0.1"
    assert replayed.profile_version == applied.profile_version
    config = service.get_config("example_candidate")
    assert sum(item.id == imported_experience.id for item in config.experience.items) == 1
    assert not next(
        item for item in config.experience.items if item.id == imported_experience.id
    ).approved
    assert (copied_candidates_root / "example_candidate" / ".history" / "1.0.0").is_dir()


def test_cv_import_rejects_invalid_dates_without_mutating_candidate(
    copied_candidates_root: Path,
) -> None:
    service = CandidateService(copied_candidates_root)
    invalid = FICTIONAL_CV.replace("2022-07", "July 2022")

    with pytest.raises(CandidateUpdateError, match="YYYY-MM"):
        service.create_cv_import("example_candidate", _request(invalid))

    assert service.get_config("example_candidate").manifest.profile_version == "1.0.0"
    assert not (copied_candidates_root / "example_candidate" / ".history").exists()


def test_empty_cv_extraction_cannot_be_applied(copied_candidates_root: Path) -> None:
    service = CandidateService(copied_candidates_root)
    draft = service.create_cv_import(
        "example_candidate",
        _request("Fictional Candidate\nSkills\nPython\n"),
    )

    with pytest.raises(CandidateUpdateError, match="no structured entries"):
        service.apply_cv_import("example_candidate", draft.import_id)


def test_cv_import_rejects_symlinked_private_staging_directory(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    candidate_directory = copied_candidates_root / "example_candidate"
    (candidate_directory / ".imports").symlink_to(tmp_path, target_is_directory=True)
    service = CandidateService(copied_candidates_root)

    with pytest.raises(CandidateUpdateError, match="directory is unsafe"):
        service.create_cv_import("example_candidate", _request())


def test_cv_import_rejects_symlinked_predictable_draft_file(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    request = _request()
    draft = extract_cv_draft("example_candidate", request)
    imports = copied_candidates_root / "example_candidate" / ".imports"
    imports.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(draft.model_dump_json(), encoding="utf-8")
    (imports / f"{draft.import_id}.json").symlink_to(outside)

    with pytest.raises(CandidateUpdateError, match="draft path is unsafe"):
        CandidateService(copied_candidates_root).create_cv_import("example_candidate", request)


def test_cv_import_caps_structured_output_amplification(copied_candidates_root: Path) -> None:
    row = "Example U | BSc | CS | Exampleton | 2020-01 | 2021-01"
    oversized = "EDUCATION\n" + "\n".join(row for _ in range(101))

    with pytest.raises(CandidateUpdateError, match="entry limit"):
        CandidateService(copied_candidates_root).create_cv_import(
            "example_candidate", _request(oversized)
        )
