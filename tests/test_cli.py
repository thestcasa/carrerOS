from __future__ import annotations

import json
from pathlib import Path

from app.__main__ import main


def test_validate_candidate_cli(
    example_candidates_root: Path, monkeypatch: object, capsys: object
) -> None:
    monkeypatch.setenv("CANDIDATES_ROOT", str(example_candidates_root))  # type: ignore[attr-defined]
    assert main(["validate-candidate", "--candidate", "example_candidate"]) == 0
    result = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert result["status"] == "valid"


def test_readiness_cli(example_candidates_root: Path, monkeypatch: object, capsys: object) -> None:
    monkeypatch.setenv("CANDIDATES_ROOT", str(example_candidates_root))  # type: ignore[attr-defined]
    assert main(["readiness", "--candidate", "example_candidate"]) == 0
    result = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert result["status"] == "ready"


def test_onboard_and_export_candidate_cli(
    copied_candidates_root: Path, monkeypatch: object, capsys: object
) -> None:
    monkeypatch.setenv("CANDIDATES_ROOT", str(copied_candidates_root))  # type: ignore[attr-defined]
    assert (
        main(
            [
                "onboard",
                "--candidate",
                "fictional_friend",
                "--display-name",
                "Fictional Friend",
            ]
        )
        == 0
    )
    onboarded = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert onboarded["status"] == "draft_unapproved"
    assert main(["export-candidate", "--candidate", "fictional_friend"]) == 0
    exported = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert exported["manifest"]["candidate_id"] == "fictional_friend"
    assert exported["identity"]["email"].endswith(".invalid")
