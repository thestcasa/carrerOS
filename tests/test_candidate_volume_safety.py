from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.candidates.service import CandidateCreateRequest, CandidateService
from app.candidates.volume_safety import (
    UnsafeCandidateTreeError,
    inspect_candidate_volume,
    stage_candidate_recovery,
)


def test_inspection_reports_difference_without_changing_mounted_data(
    tmp_path: Path, example_candidates_root: Path
) -> None:
    mounted_root = tmp_path / "mounted"
    fixture_root = tmp_path / "fixtures"
    shutil.copytree(example_candidates_root, mounted_root)
    shutil.copytree(example_candidates_root, fixture_root)
    mounted_file = mounted_root / "example_candidate" / "biography.json"
    original = mounted_file.read_bytes()
    mounted_file.write_text('{"preserved": "unknown fictional customization"}\n', encoding="utf-8")
    customized = mounted_file.read_bytes()

    report = inspect_candidate_volume(mounted_root, fixture_root)

    assert report.status == "different"
    assert report.mutation_performed is False
    assert report.mounted_sha256 != report.fixture_sha256
    assert "biography.json" in report.changed_paths
    assert mounted_file.read_bytes() == customized
    assert mounted_file.read_bytes() != original


def test_inspection_rejects_a_mounted_symlink_without_following_it(
    tmp_path: Path, example_candidates_root: Path
) -> None:
    mounted_root = tmp_path / "mounted"
    mounted_root.mkdir()
    (mounted_root / "example_candidate").symlink_to(
        example_candidates_root / "example_candidate", target_is_directory=True
    )

    report = inspect_candidate_volume(mounted_root, example_candidates_root)

    assert report.status == "unsafe"
    assert report.mutation_performed is False


def test_recovery_is_staged_outside_candidate_volume_and_never_overwrites(
    tmp_path: Path, example_candidates_root: Path
) -> None:
    destination_root = tmp_path / "review-only-recovery"
    report = stage_candidate_recovery(example_candidates_root, destination_root)
    staged_profile = destination_root / "example_candidate" / "profile.yaml"

    assert report.status == "staged"
    assert report.mutation_performed_on_candidate_volume is False
    assert staged_profile.is_file()
    with pytest.raises(FileExistsError, match="nothing was overwritten"):
        stage_candidate_recovery(example_candidates_root, destination_root)


@pytest.mark.parametrize("candidate_id", ("../example_candidate", "/tmp/example", "UPPER"))
def test_volume_operations_reject_unsafe_candidate_identifiers(
    tmp_path: Path, example_candidates_root: Path, candidate_id: str
) -> None:
    destination_root = tmp_path / "review-only-recovery"
    inspection = inspect_candidate_volume(
        example_candidates_root, example_candidates_root, candidate_id
    )
    assert inspection.status == "unsafe"
    assert inspection.mutation_performed is False
    with pytest.raises(UnsafeCandidateTreeError, match="safe lowercase identifier"):
        stage_candidate_recovery(example_candidates_root, destination_root, candidate_id)
    assert not destination_root.exists()


def test_recovery_does_not_copy_ignored_unvalidated_directories(
    tmp_path: Path, example_candidates_root: Path
) -> None:
    fixture_root = tmp_path / "fixtures"
    shutil.copytree(example_candidates_root, fixture_root)
    outside = tmp_path / "outside.txt"
    outside.write_text("fictional private import", encoding="utf-8")
    imports = fixture_root / "example_candidate" / ".imports"
    imports.mkdir()
    (imports / "outside-link").symlink_to(outside)
    destination_root = tmp_path / "review-only-recovery"

    stage_candidate_recovery(fixture_root, destination_root)

    assert not (destination_root / "example_candidate" / ".imports").exists()
    assert outside.read_text(encoding="utf-8") == "fictional private import"


def test_recovery_rejects_a_validated_tree_symlink_without_leaving_a_partial_copy(
    tmp_path: Path, example_candidates_root: Path
) -> None:
    fixture_root = tmp_path / "fixtures"
    shutil.copytree(example_candidates_root, fixture_root)
    outside = tmp_path / "outside.txt"
    outside.write_text("fictional external content", encoding="utf-8")
    (fixture_root / "example_candidate" / "unsafe-link").symlink_to(outside)
    destination_root = tmp_path / "review-only-recovery"

    with pytest.raises(UnsafeCandidateTreeError, match="symlink is not allowed"):
        stage_candidate_recovery(fixture_root, destination_root)

    assert not (destination_root / "example_candidate").exists()


def test_recovery_rejects_a_destination_inside_the_source_tree(
    example_candidates_root: Path,
) -> None:
    nested_destination = example_candidates_root / "example_candidate" / "recovery"
    with pytest.raises(ValueError, match="outside the candidate source tree"):
        stage_candidate_recovery(example_candidates_root, nested_destination)
    assert not nested_destination.exists()


def test_onboarding_uses_immutable_fixture_instead_of_stale_mounted_example(
    tmp_path: Path, example_candidates_root: Path
) -> None:
    mounted_root = tmp_path / "mounted"
    fixture_root = tmp_path / "fixtures"
    shutil.copytree(example_candidates_root, mounted_root)
    shutil.copytree(example_candidates_root, fixture_root)
    stale_scoring = mounted_root / "example_candidate" / "scoring_rules.json"
    stale_scoring.write_text(
        json.dumps(
            {
                "application_threshold": 1,
                "human_review_threshold": 1,
                "weights": {"role_alignment": 1.0},
                "bonuses": [],
                "penalties": [],
                "approved": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    expected = json.loads(
        (fixture_root / "example_candidate" / "scoring_rules.json").read_text(encoding="utf-8")
    )

    service = CandidateService(mounted_root, fixture_root)
    detail = service.create(
        CandidateCreateRequest(
            candidate_id="recovered_candidate",
            display_name="Recovered Fictional Candidate",
        ),
        "trusted-fixture-recovery",
    )
    recovered = json.loads(
        (mounted_root / "recovered_candidate" / "scoring_rules.json").read_text(encoding="utf-8")
    )

    assert detail.candidate_id == "recovered_candidate"
    assert recovered["application_threshold"] == expected["application_threshold"]
    assert recovered["weights"] == expected["weights"]
    assert json.loads(stale_scoring.read_text(encoding="utf-8"))["application_threshold"] == 1
