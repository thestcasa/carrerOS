from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


class CandidatePathError(ValueError):
    pass


@dataclass(frozen=True)
class CandidateSessionPaths:
    root: Path

    def _candidate_root(self, candidate_id: str) -> Path:
        if re.fullmatch(r"[a-z][a-z0-9_]{2,63}", candidate_id) is None:
            raise CandidatePathError("candidate_id contains unsafe path characters")
        runtime_root = self.root.resolve()
        candidates_root = runtime_root / "candidates"
        candidate_root = candidates_root / candidate_id
        for path, expected_parent in (
            (candidates_root, runtime_root),
            (candidate_root, candidates_root),
        ):
            if path.is_symlink():
                raise CandidatePathError("candidate session path contains a symlink")
            if path.exists() and (not path.is_dir() or path.resolve().parent != expected_parent):
                raise CandidatePathError("candidate session path is unsafe")
        if candidate_root.parent != candidates_root:
            raise CandidatePathError("candidate session escaped runtime root")
        return candidate_root

    @staticmethod
    def _candidate_child(candidate_root: Path, name: str) -> Path:
        child = candidate_root / name
        if child.is_symlink():
            raise CandidatePathError("candidate session path contains a symlink")
        if child.exists() and (not child.is_dir() or child.resolve().parent != candidate_root):
            raise CandidatePathError("candidate session path is unsafe")
        return child

    def session_directory(self, candidate_id: str, session_id: UUID) -> Path:
        candidate_root = self._candidate_root(candidate_id)
        sessions_root = self._candidate_child(candidate_root, "sessions")
        return self._candidate_child(sessions_root, str(session_id))

    def allowed_artifact_root(self, candidate_id: str) -> Path:
        candidate_root = self._candidate_root(candidate_id)
        return self._candidate_child(candidate_root, "application_archive")
