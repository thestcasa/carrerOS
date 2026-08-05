from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.archive import canonical_json_bytes, sha256_bytes
from app.materials.contracts import DraftArtifactManifest, GeneratedDocument


class DraftVersionExistsError(FileExistsError):
    pass


class DraftArtifactStore:
    """Candidate-isolated append-only storage for versioned draft documents."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def save(
        self, *, candidate_id: str, application_id: UUID, version: int, document: GeneratedDocument
    ) -> Path:
        if version < 1:
            raise ValueError("version must be positive")
        if not candidate_id or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in candidate_id
        ):
            raise ValueError("candidate_id contains invalid characters")
        directory = self._root / candidate_id / str(application_id) / document.kind.value
        directory.mkdir(parents=True, exist_ok=True)
        final_path = directory / f"v{version}.json"
        if final_path.exists():
            raise DraftVersionExistsError(f"draft version already exists: {final_path}")
        payload = canonical_json_bytes(document.model_dump(mode="json"))
        manifest = DraftArtifactManifest(
            candidate_id=candidate_id,
            application_id=application_id,
            kind=document.kind,
            version=version,
            created_at=datetime.now(UTC),
            payload_sha256=sha256_bytes(payload),
        )
        envelope = canonical_json_bytes(
            {
                "manifest": manifest.model_dump(mode="json"),
                "document": document.model_dump(mode="json"),
            }
        )
        descriptor, temporary_name = tempfile.mkstemp(prefix=".draft-", dir=directory)
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(envelope)
                temporary.flush()
                os.fsync(temporary.fileno())
            try:
                os.link(temporary_name, final_path)
            except FileExistsError as exc:
                raise DraftVersionExistsError(
                    f"draft version already exists: {final_path}"
                ) from exc
        finally:
            Path(temporary_name).unlink(missing_ok=True)
        return final_path

    @staticmethod
    def verify(path: Path) -> bool:
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            manifest = DraftArtifactManifest.model_validate(envelope["manifest"])
            document = GeneratedDocument.model_validate(envelope["document"])
        except (KeyError, OSError, ValueError, TypeError):
            return False
        payload = canonical_json_bytes(document.model_dump(mode="json"))
        return manifest.payload_sha256 == sha256_bytes(payload)
