from __future__ import annotations

import json
from pathlib import Path


def test_committed_candidate_fixture_is_explicitly_fictional(project_root: Path) -> None:
    candidates_root = project_root / "candidates"
    identity_files = list(candidates_root.glob("*/identity.json"))
    assert identity_files
    for identity_path in identity_files:
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        assert "example" in identity["full_name"].casefold()
        assert identity["email"].endswith(".invalid")


def test_committed_fixtures_do_not_contain_known_real_candidate_markers(project_root: Path) -> None:
    fixture_text = "\n".join(
        path.read_text(encoding="utf-8").casefold()
        for path in (project_root / "candidates").rglob("*.json")
    )
    forbidden_markers = ("aless", "@gmail.", "@outlook.", "politecnico di torino")
    assert all(marker not in fixture_text for marker in forbidden_markers)
