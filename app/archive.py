from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ArchiveExistsError(FileExistsError):
    pass


class ArchiveManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    candidate_id: str
    application_id: UUID
    created_at: datetime
    files: dict[str, str]


class ApplicationArchiveData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    candidate_snapshot: Any
    job_snapshot: Any
    scoring_results: Any
    generated_document_references: Any
    answers: Any
    validation_report: Any
    event_log: Any


_PAYLOAD_NAMES = (
    "candidate_snapshot",
    "job_snapshot",
    "scoring_results",
    "generated_document_references",
    "answers",
    "validation_report",
    "event_log",
)


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, set | frozenset | tuple):
        return list(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            default=_json_default,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class ApplicationArchiveBuilder:
    def __init__(self, archives_root: Path) -> None:
        self._root = archives_root.resolve()

    def create(
        self,
        *,
        candidate_id: str,
        application_id: UUID,
        data: ApplicationArchiveData,
    ) -> Path:
        if not candidate_id or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in candidate_id
        ):
            raise ValueError("candidate_id contains invalid characters")
        candidate_root = self._root / candidate_id
        final_path = candidate_root / str(application_id)
        candidate_root.mkdir(parents=True, exist_ok=True)
        if final_path.exists():
            raise ArchiveExistsError(f"archive already exists: {final_path}")

        temp_path = Path(tempfile.mkdtemp(prefix=".building-", dir=candidate_root))
        try:
            hashes: dict[str, str] = {}
            for name in _PAYLOAD_NAMES:
                filename = f"{name}.json"
                content = canonical_json_bytes(getattr(data, name))
                (temp_path / filename).write_bytes(content)
                hashes[filename] = sha256_bytes(content)
            manifest = ArchiveManifest(
                schema_version="1.0",
                candidate_id=candidate_id,
                application_id=application_id,
                created_at=datetime.now(UTC),
                files=hashes,
            )
            (temp_path / "manifest.json").write_bytes(
                canonical_json_bytes(manifest.model_dump(mode="json"))
            )
            temp_path.rename(final_path)
        except Exception:
            if temp_path.exists():
                shutil.rmtree(temp_path)
            raise
        return final_path

    @staticmethod
    def verify(archive_path: Path) -> bool:
        try:
            manifest = ArchiveManifest.model_validate_json(
                (archive_path / "manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return False
        actual_files = {
            path.name
            for path in archive_path.iterdir()
            if path.is_file() and path.name != "manifest.json"
        }
        if actual_files != set(manifest.files):
            return False
        for filename, expected_hash in manifest.files.items():
            try:
                content = (archive_path / filename).read_bytes()
            except OSError:
                return False
            if sha256_bytes(content) != expected_hash:
                return False
        return True
