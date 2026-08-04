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
