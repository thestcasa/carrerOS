from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.candidates.models import CandidateConfig


class CandidateSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: UUID
    candidate_id: str
    profile_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    created_at: datetime
    config_json: str
    config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_file_sha256: tuple[tuple[str, str], ...]


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _hash_files(directory: Path, filenames: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    hashes: list[tuple[str, str]] = []
    for filename in sorted(filenames):
        source_path = (directory / filename).resolve()
        if source_path.parent != directory or not source_path.is_file():
            raise ValueError(f"candidate snapshot source is missing or unsafe: {filename}")
        hashes.append((filename, _sha256(source_path.read_bytes())))
    return tuple(hashes)


def _source_hashes(
    config: CandidateConfig, candidate_directory: Path | None
) -> tuple[tuple[str, str], ...]:
    if candidate_directory is None:
        return ()
    directory = candidate_directory.resolve()
    filenames = (
        "profile.yaml",
        *(
            getattr(config.manifest.data_files, field_name)
            for field_name in type(config.manifest.data_files).model_fields
        ),
    )
    return _hash_files(directory, filenames)


def build_candidate_snapshot(
    config: CandidateConfig,
    *,
    candidate_directory: Path | None = None,
) -> CandidateSnapshot:
    config_json = json.dumps(
        config.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    source_hashes = _source_hashes(config, candidate_directory)
    return CandidateSnapshot(
        snapshot_id=uuid4(),
        candidate_id=config.manifest.candidate_id,
        profile_version=config.manifest.profile_version,
        created_at=datetime.now(UTC),
        config_json=config_json,
        config_sha256=_sha256(config_json.encode("utf-8")),
        source_file_sha256=source_hashes,
    )
