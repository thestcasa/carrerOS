from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


class CandidatePathError(ValueError):
    pass


@dataclass(frozen=True)
class CandidateSessionPaths:
    root: Path

    def session_directory(self, candidate_id: str, session_id: UUID) -> Path:
        if not candidate_id or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for character in candidate_id
        ):
            raise CandidatePathError("candidate_id contains unsafe path characters")
        candidate_root = (self.root / "candidates" / candidate_id).resolve()
        runtime_root = self.root.resolve()
        if candidate_root.parent.parent != runtime_root:
            raise CandidatePathError("candidate session escaped runtime root")
        return candidate_root / "sessions" / str(session_id)

    def allowed_artifact_root(self, candidate_id: str) -> Path:
        session_parent = self.session_directory(candidate_id, UUID(int=0)).parents[1]
        return session_parent / "application_archive"
