from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

_IGNORED_DIRECTORIES = frozenset({".history", ".idempotency", ".locks", ".imports"})
_MAX_FILE_BYTES = 8 * 1024 * 1024
_MAX_TREE_BYTES = 64 * 1024 * 1024
_MAX_CHANGED_PATHS = 50
_CANDIDATE_ID_PATTERN = re.compile(r"[a-z][a-z0-9_]{2,63}")


class CandidateVolumeInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    status: Literal["match", "different", "mounted_missing", "fixture_missing", "unsafe"]
    mounted_sha256: str | None
    fixture_sha256: str | None
    changed_paths: tuple[str, ...]
    detail: str
    mutation_performed: bool = False


class CandidateRecoveryStage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    status: Literal["staged"]
    destination: str
    fixture_sha256: str
    mutation_performed_on_candidate_volume: bool = False


class UnsafeCandidateTreeError(ValueError):
    pass


def _candidate_path(root: Path, candidate_id: str) -> Path:
    if _CANDIDATE_ID_PATTERN.fullmatch(candidate_id) is None:
        raise UnsafeCandidateTreeError("candidate_id must be a safe lowercase identifier")
    resolved_root = root.resolve()
    candidate_path = resolved_root / candidate_id
    if candidate_path.parent != resolved_root or not candidate_path.is_relative_to(resolved_root):
        raise UnsafeCandidateTreeError("candidate path escapes its configured root")
    return candidate_path


def _file_manifest(root: Path) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir():
        raise UnsafeCandidateTreeError("candidate path must be a regular directory")
    resolved_root = root.resolve(strict=True)
    manifest: dict[str, str] = {}
    total_bytes = 0
    pending = [resolved_root]
    while pending:
        directory = pending.pop()
        for entry in sorted(os.scandir(directory), key=lambda item: item.name):
            relative = Path(entry.path).relative_to(resolved_root)
            if entry.is_symlink():
                raise UnsafeCandidateTreeError(f"symlink is not allowed: {relative.as_posix()}")
            mode = entry.stat(follow_symlinks=False).st_mode
            if stat.S_ISDIR(mode):
                if entry.name not in _IGNORED_DIRECTORIES:
                    pending.append(Path(entry.path))
                continue
            if not stat.S_ISREG(mode):
                raise UnsafeCandidateTreeError(
                    f"non-regular entry is not allowed: {relative.as_posix()}"
                )
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(entry.path, flags)
            except OSError as exc:
                raise UnsafeCandidateTreeError(
                    f"candidate file could not be opened safely: {relative.as_posix()}"
                ) from exc
            try:
                opened = os.fstat(descriptor)
                if not stat.S_ISREG(opened.st_mode) or opened.st_ino != entry.inode():
                    raise UnsafeCandidateTreeError(
                        f"candidate file changed during inspection: {relative.as_posix()}"
                    )
                size = opened.st_size
                if size > _MAX_FILE_BYTES:
                    raise UnsafeCandidateTreeError(
                        f"candidate file is too large: {relative.as_posix()}"
                    )
                total_bytes += size
                if total_bytes > _MAX_TREE_BYTES:
                    raise UnsafeCandidateTreeError("candidate tree is too large to inspect safely")
                content_digest = hashlib.sha256()
                while block := os.read(descriptor, 64 * 1024):
                    content_digest.update(block)
                manifest[relative.as_posix()] = content_digest.hexdigest()
            finally:
                os.close(descriptor)
    return manifest


def _ignore_unvalidated_directories(_directory: str, names: list[str]) -> frozenset[str]:
    return _IGNORED_DIRECTORIES.intersection(names)


def _manifest_sha256(manifest: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for path, content_sha256 in sorted(manifest.items()):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content_sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def inspect_candidate_volume(
    candidates_root: Path,
    fixture_root: Path,
    candidate_id: str = "example_candidate",
) -> CandidateVolumeInspection:
    try:
        mounted = _candidate_path(candidates_root, candidate_id)
        fixture = _candidate_path(fixture_root, candidate_id)
    except UnsafeCandidateTreeError as exc:
        return CandidateVolumeInspection(
            candidate_id=candidate_id,
            status="unsafe",
            mounted_sha256=None,
            fixture_sha256=None,
            changed_paths=(),
            detail=f"Candidate comparison stopped without mutation: {exc}",
        )
    if fixture.is_symlink() or not fixture.exists():
        return CandidateVolumeInspection(
            candidate_id=candidate_id,
            status="fixture_missing",
            mounted_sha256=None,
            fixture_sha256=None,
            changed_paths=(),
            detail="The immutable image fixture is unavailable; mounted data was not changed.",
        )
    if mounted.is_symlink():
        return CandidateVolumeInspection(
            candidate_id=candidate_id,
            status="unsafe",
            mounted_sha256=None,
            fixture_sha256=None,
            changed_paths=(),
            detail="Mounted candidate is a symlink; comparison stopped without mutation.",
        )
    if not mounted.exists():
        try:
            fixture_sha256 = _manifest_sha256(_file_manifest(fixture))
        except UnsafeCandidateTreeError as exc:
            return CandidateVolumeInspection(
                candidate_id=candidate_id,
                status="unsafe",
                mounted_sha256=None,
                fixture_sha256=None,
                changed_paths=(),
                detail=f"Immutable fixture inspection failed safely: {exc}",
            )
        return CandidateVolumeInspection(
            candidate_id=candidate_id,
            status="mounted_missing",
            mounted_sha256=None,
            fixture_sha256=fixture_sha256,
            changed_paths=(),
            detail="The mounted candidate is absent; no fixture was copied automatically.",
        )
    try:
        mounted_manifest = _file_manifest(mounted)
        fixture_manifest = _file_manifest(fixture)
    except UnsafeCandidateTreeError as exc:
        return CandidateVolumeInspection(
            candidate_id=candidate_id,
            status="unsafe",
            mounted_sha256=None,
            fixture_sha256=None,
            changed_paths=(),
            detail=f"Candidate comparison stopped without mutation: {exc}",
        )
    mounted_sha256 = _manifest_sha256(mounted_manifest)
    fixture_sha256 = _manifest_sha256(fixture_manifest)
    paths = sorted(set(mounted_manifest) | set(fixture_manifest))
    changed = tuple(
        path for path in paths if mounted_manifest.get(path) != fixture_manifest.get(path)
    )[:_MAX_CHANGED_PATHS]
    if mounted_sha256 == fixture_sha256:
        return CandidateVolumeInspection(
            candidate_id=candidate_id,
            status="match",
            mounted_sha256=mounted_sha256,
            fixture_sha256=fixture_sha256,
            changed_paths=(),
            detail="Mounted fictional candidate matches the immutable image fixture.",
        )
    return CandidateVolumeInspection(
        candidate_id=candidate_id,
        status="different",
        mounted_sha256=mounted_sha256,
        fixture_sha256=fixture_sha256,
        changed_paths=changed,
        detail=(
            "Mounted data differs from the immutable fixture and was preserved. Export or back up "
            "the mounted candidate before reviewing a staged recovery copy."
        ),
    )


def stage_candidate_recovery(
    fixture_root: Path,
    destination_root: Path,
    candidate_id: str = "example_candidate",
) -> CandidateRecoveryStage:
    source = _candidate_path(fixture_root, candidate_id)
    resolved_destination_root = destination_root.resolve()
    if resolved_destination_root == source or resolved_destination_root.is_relative_to(source):
        raise ValueError("recovery destination must be outside the candidate source tree")
    destination_root.mkdir(parents=True, exist_ok=True)
    resolved_destination_root = destination_root.resolve(strict=True)
    if not resolved_destination_root.is_dir():
        raise ValueError("recovery destination root must be a directory")
    destination = _candidate_path(resolved_destination_root, candidate_id)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("recovery destination already exists; nothing was overwritten")
    manifest = _file_manifest(source)
    try:
        shutil.copytree(
            source,
            destination,
            symlinks=True,
            ignore=_ignore_unvalidated_directories,
        )
        copied_manifest = _file_manifest(destination)
        if copied_manifest != manifest:
            raise UnsafeCandidateTreeError("recovery copy does not match the validated fixture")
    except Exception:
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        elif destination.is_symlink():
            destination.unlink()
        raise
    return CandidateRecoveryStage(
        candidate_id=candidate_id,
        status="staged",
        destination=str(destination),
        fixture_sha256=_manifest_sha256(manifest),
    )
