from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from app.candidates.loader import CandidateConfigError, CandidateLoader
from app.candidates.readiness import assess_readiness


def _rewrite(path: Path, mutate: Any) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_example_candidate_is_valid_and_ready(example_candidates_root: Path) -> None:
    config = CandidateLoader(example_candidates_root).load("example_candidate")

    assert config.manifest.candidate_id == "example_candidate"
    assert assess_readiness(config).status == "ready"


def test_invalid_candidate_configuration_is_rejected(copied_candidates_root: Path) -> None:
    identity_path = copied_candidates_root / "example_candidate" / "identity.json"
    _rewrite(identity_path, lambda data: data.update({"unsupported_field": "not allowed"}))

    with pytest.raises(CandidateConfigError, match="unsupported_field"):
        CandidateLoader(copied_candidates_root).load("example_candidate")


def test_incorrect_dates_are_rejected(copied_candidates_root: Path) -> None:
    education_path = copied_candidates_root / "example_candidate" / "education.json"

    def reverse_dates(data: dict[str, Any]) -> None:
        data["items"][0]["end_date"] = "2017-01-01"

    _rewrite(education_path, reverse_dates)

    with pytest.raises(CandidateConfigError, match="end_date"):
        CandidateLoader(copied_candidates_root).load("example_candidate")


def test_duplicate_project_ids_are_rejected(copied_candidates_root: Path) -> None:
    projects_path = copied_candidates_root / "example_candidate" / "projects.json"

    def duplicate_project(data: dict[str, Any]) -> None:
        data["items"].append(dict(data["items"][0]))

    _rewrite(projects_path, duplicate_project)

    with pytest.raises(CandidateConfigError, match="duplicate project IDs"):
        CandidateLoader(copied_candidates_root).load("example_candidate")


def test_path_traversal_candidate_id_is_rejected(example_candidates_root: Path) -> None:
    with pytest.raises(CandidateConfigError, match="invalid characters"):
        CandidateLoader(example_candidates_root).load("../example_candidate")


def test_optional_candidate_domains_may_be_omitted(copied_candidates_root: Path) -> None:
    candidate_dir = copied_candidates_root / "example_candidate"
    profile_path = candidate_dir / "profile.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    for key in ("certifications", "publications", "notification_rules"):
        profile["data_files"].pop(key)
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")

    config = CandidateLoader(copied_candidates_root).load("example_candidate")

    assert config.certifications.items == ()
    assert config.publications.items == ()
    report = assess_readiness(config)
    optional = {
        domain.domain: domain.status
        for domain in report.domains
        if domain.domain in {"certifications", "publications", "notifications"}
    }
    assert set(optional.values()) == {"NOT_CONFIGURED"}


@pytest.mark.parametrize(
    ("filename", "expected"),
    (
        ("education.json", "duplicate education IDs"),
        ("experience.json", "duplicate experience IDs"),
        ("certifications.json", "duplicate certification IDs"),
    ),
)
def test_candidate_fact_ids_must_be_unique(
    copied_candidates_root: Path, filename: str, expected: str
) -> None:
    path = copied_candidates_root / "example_candidate" / filename

    def duplicate_item(data: dict[str, Any]) -> None:
        data["items"].append(dict(data["items"][0]))

    _rewrite(path, duplicate_item)

    with pytest.raises(CandidateConfigError, match=expected):
        CandidateLoader(copied_candidates_root).load("example_candidate")


def test_fact_level_approval_blocks_readiness(copied_candidates_root: Path) -> None:
    biography_path = copied_candidates_root / "example_candidate" / "biography.json"
    _rewrite(biography_path, lambda data: data.update({"approved": False}))

    report = assess_readiness(CandidateLoader(copied_candidates_root).load("example_candidate"))

    assert report.status == "not_ready"
    assert "biography_not_approved" in {issue.code for issue in report.issues}
