from __future__ import annotations

import hashlib
from pathlib import Path

from app.candidates.loader import CandidateLoader
from app.candidates.snapshot import build_candidate_snapshot


def test_candidate_snapshot_is_canonical_and_hashes_all_sources(
    example_candidates_root: Path,
) -> None:
    config = CandidateLoader(example_candidates_root).load("example_candidate")
    candidate_directory = example_candidates_root / "example_candidate"

    first = build_candidate_snapshot(config, candidate_directory=candidate_directory)
    second = build_candidate_snapshot(config, candidate_directory=candidate_directory)

    assert first.candidate_id == "example_candidate"
    assert first.config_json == second.config_json
    assert first.config_sha256 == second.config_sha256
    assert first.config_sha256 == hashlib.sha256(first.config_json.encode("utf-8")).hexdigest()
    assert len(first.source_file_sha256) == 20
    assert first.snapshot_id != second.snapshot_id
