from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from app.candidates.portability import CandidatePortabilityError
from app.candidates.service import (
    CandidateConfigurationImportRequest,
    CandidateIdempotencyError,
    CandidateSectionUpdate,
    CandidateService,
)


def _request(content: str, expected_version: str) -> CandidateConfigurationImportRequest:
    return CandidateConfigurationImportRequest(
        format="json",
        content=content,
        expected_profile_version=expected_version,
    )


def test_whole_configuration_import_is_atomic_versioned_and_idempotent(
    copied_candidates_root: Path,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source-candidates"
    shutil.copytree(copied_candidates_root, source_root)
    profile_path = source_root / "example_candidate" / "profile.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["active"] = False
    profile["workflow"]["automatic_submission_enabled"] = True
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    source = CandidateService(source_root)
    source.update_section(
        "example_candidate",
        CandidateSectionUpdate(
            section="biography",
            data={
                **source.export("example_candidate")["biography"],
                "summary": "Portable fictional candidate summary.",
            },
        ),
        "source-biography-change",
    )
    source.update_section(
        "example_candidate",
        CandidateSectionUpdate(
            section="skills",
            data={
                **source.export("example_candidate")["skills"],
                "categories": {"platform": ["Python", "SQL"]},
            },
        ),
        "source-skills-change",
    )
    content = source.export_configuration("example_candidate", "json")

    destination = CandidateService(copied_candidates_root)
    result = destination.import_configuration(
        "example_candidate",
        _request(content, "1.0.0"),
        "portable-import-main",
    )
    replayed = destination.import_configuration(
        "example_candidate",
        _request(content, "1.0.0"),
        "portable-import-main",
    )

    assert replayed == result
    assert result.previous_version == "1.0.0"
    assert result.profile_version == "1.0.1"
    assert result.source_profile_version == "1.0.2"
    assert result.changed is True
    assert result.imported_sections == ("biography", "skills")
    imported = destination.get_config("example_candidate")
    source_config = source.get_config("example_candidate")
    assert imported.model_dump(exclude={"manifest"}) == source_config.model_dump(
        exclude={"manifest"}
    )
    assert imported.manifest.active is True
    assert imported.manifest.workflow.automatic_submission_enabled is False
    for section in result.imported_sections:
        assert getattr(imported, section) == getattr(source_config, section)
    history = copied_candidates_root / "example_candidate" / ".history"
    assert sorted(path.name for path in history.iterdir()) == ["1.0.0"]


def test_configuration_import_rejects_conflicts_without_mutation(
    copied_candidates_root: Path,
) -> None:
    service = CandidateService(copied_candidates_root)
    content = service.export_configuration("example_candidate", "json")
    request = _request(content, "1.0.0")
    original = service.get_config("example_candidate")

    with pytest.raises(CandidateIdempotencyError):
        service.import_configuration(
            "example_candidate",
            _request(content, "0.9.0"),
            "portable-import-stale",
        )

    service.import_configuration("example_candidate", request, "portable-import-shared")
    with pytest.raises(CandidateIdempotencyError):
        service.import_configuration(
            "example_candidate",
            _request(content, "1.0.1"),
            "portable-import-shared",
        )

    assert service.get_config("example_candidate") == original
    assert not (copied_candidates_root / "example_candidate" / ".history").exists()


def test_invalid_configuration_bundle_leaves_no_history_or_receipt(
    copied_candidates_root: Path,
) -> None:
    service = CandidateService(copied_candidates_root)
    content = json.loads(service.export_configuration("example_candidate", "json"))
    content["configuration"]["biography"]["summary"] = "Tampered"

    with pytest.raises(CandidatePortabilityError):
        service.import_configuration(
            "example_candidate",
            _request(json.dumps(content), "1.0.0"),
            "portable-invalid-bundle",
        )

    candidate = copied_candidates_root / "example_candidate"
    assert service.get_config("example_candidate").manifest.profile_version == "1.0.0"
    assert not (candidate / ".history").exists()
    receipt_root = copied_candidates_root / ".command_receipts"
    assert not receipt_root.exists() or not tuple(receipt_root.iterdir())


def test_noop_configuration_import_does_not_create_history(
    copied_candidates_root: Path,
) -> None:
    service = CandidateService(copied_candidates_root)
    content = service.export_configuration("example_candidate", "yaml")

    result = service.import_configuration(
        "example_candidate",
        CandidateConfigurationImportRequest(
            format="yaml",
            content=content,
            expected_profile_version="1.0.0",
        ),
        "portable-noop-import",
    )

    assert result.changed is False
    assert result.profile_version == "1.0.0"
    assert result.imported_sections == ()
    assert not (copied_candidates_root / "example_candidate" / ".history").exists()
