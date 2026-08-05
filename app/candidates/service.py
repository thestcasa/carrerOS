from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, ValidationError

from app.candidates.cv_import import CVImportDraft, CVImportError, CVImportRequest, extract_cv_draft
from app.candidates.loader import CandidateConfigError, CandidateLoader
from app.candidates.models import (
    ApprovedAnswers,
    Biography,
    CandidateConfig,
    CareerStrategy,
    Certifications,
    CompanyRules,
    CoverLetterRules,
    CVRules,
    Education,
    Experience,
    Identity,
    Languages,
    LegalStatus,
    NotificationRules,
    Preferences,
    Projects,
    Publications,
    RoleRules,
    ScoringRules,
    Skills,
)
from app.candidates.readiness import ReadinessReport, assess_readiness
from app.candidates.snapshot import CandidateSnapshot, build_candidate_snapshot

CandidateSection = Literal[
    "identity",
    "biography",
    "education",
    "experience",
    "projects",
    "skills",
    "languages",
    "career_strategy",
    "scoring_rules",
    "preferences",
    "legal_status",
    "approved_answers",
    "cv_rules",
    "cover_letter_rules",
    "companies",
    "roles",
    "certifications",
    "publications",
    "notification_rules",
]

_SECTION_MODELS: dict[CandidateSection, type[BaseModel]] = {
    "identity": Identity,
    "biography": Biography,
    "education": Education,
    "experience": Experience,
    "projects": Projects,
    "skills": Skills,
    "languages": Languages,
    "career_strategy": CareerStrategy,
    "scoring_rules": ScoringRules,
    "preferences": Preferences,
    "legal_status": LegalStatus,
    "approved_answers": ApprovedAnswers,
    "cv_rules": CVRules,
    "cover_letter_rules": CoverLetterRules,
    "companies": CompanyRules,
    "roles": RoleRules,
    "certifications": Certifications,
    "publications": Publications,
    "notification_rules": NotificationRules,
}


class CandidateNotFoundError(CandidateConfigError):
    pass


class CandidateUpdateError(CandidateConfigError):
    pass


class CandidateSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    display_name: str
    profile_version: str | None
    configuration_status: Literal["valid", "invalid"]
    readiness_status: Literal["ready", "not_ready", "invalid"]
    automation_status: Literal["disabled", "autonomous", "unknown"]


class CandidateDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    profile_version: str
    config: dict[str, Any]
    readiness: ReadinessReport


class CandidateSectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section: CandidateSection
    data: dict[str, Any]


class CandidateUpdateResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    previous_version: str
    profile_version: str
    section: CandidateSection
    readiness: ReadinessReport


class CandidateValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    status: Literal["VALID", "BLOCKING_ERROR"]
    profile_version: str
    issues: tuple[dict[str, Any], ...]


class CandidateCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    display_name: str


class CandidateImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    section: CandidateSection
    data: dict[str, Any]


def _next_patch_version(version: str) -> str:
    major, minor, patch = (int(part) for part in version.split("."))
    return f"{major}.{minor}.{patch + 1}"


class CandidateService:
    def __init__(self, candidates_root: Path) -> None:
        self._root = candidates_root.resolve()
        self._loader = CandidateLoader(self._root)
        self._write_lock = threading.RLock()
        self._held_lifecycle_locks = threading.local()

    def create(self, request: CandidateCreateRequest) -> CandidateDetail:
        if re.fullmatch(r"[a-z][a-z0-9_]{2,63}", request.candidate_id) is None:
            raise CandidateUpdateError("candidate_id must be a safe lowercase identifier")
        with self._write_lock, self._lifecycle_lock(request.candidate_id):
            self._assert_not_deleted(request.candidate_id)
            return self._create_unlocked(request)

    def _create_unlocked(self, request: CandidateCreateRequest) -> CandidateDetail:
        if not request.display_name.strip():
            raise CandidateUpdateError("display_name must not be empty")
        source = self._root / "example_candidate"
        destination = self._root / request.candidate_id
        if destination.exists():
            raise CandidateUpdateError("candidate already exists")
        if not source.is_dir():
            raise CandidateUpdateError("fictional onboarding template is unavailable")
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".history"))
        try:
            profile_path = destination / "profile.yaml"
            profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
            profile["candidate_id"] = request.candidate_id
            profile["display_name"] = request.display_name.strip()
            profile["profile_version"] = "0.1.0"
            profile["workflow"].update(
                {
                    "discovery_enabled": False,
                    "automatic_submission_enabled": False,
                    "email_tracking_enabled": False,
                }
            )
            profile["validation"] = {
                "profile_approved": False,
                "legal_status_approved": False,
                "automatic_answers_approved": False,
                "cv_templates_approved": False,
            }
            profile_path.write_text(
                yaml.safe_dump(profile, sort_keys=False, allow_unicode=True), encoding="utf-8"
            )
            identity_path = destination / "identity.json"
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
            identity.update(
                {
                    "candidate_id": request.candidate_id,
                    "full_name": request.display_name.strip(),
                    "email": f"onboarding@{request.candidate_id}.invalid",
                    "phone": "+0 000 000",
                    "city": "Unapproved",
                    "country_code": "ZZ",
                    "approved": False,
                }
            )
            identity_path.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
            biography_path = destination / "biography.json"
            biography_path.write_text(
                json.dumps(
                    {
                        "summary": "Unapproved onboarding draft; replace with candidate facts.",
                        "highlights": ["Unapproved draft evidence"],
                        "approved": False,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            legal_path = destination / "legal_status.json"
            legal_path.write_text(
                json.dumps(
                    {
                        "jurisdictions": ["UNAPPROVED"],
                        "work_authorization_confirmed": False,
                        "requires_sponsorship": False,
                        "approved_for_automated_use": False,
                        "approved": False,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            draft_sections: dict[str, dict[str, Any]] = {
                "education.json": {"items": []},
                "experience.json": {"items": []},
                "projects.json": {"items": []},
                "certifications.json": {"items": []},
                "publications.json": {"items": []},
                "languages.json": {"items": []},
                "approved_answers.json": {"items": []},
            }
            for filename, payload in draft_sections.items():
                (destination / filename).write_text(
                    json.dumps(payload, indent=2) + "\n", encoding="utf-8"
                )
            for filename in (
                "skills.json",
                "career_strategy.json",
                "scoring_rules.json",
                "preferences.json",
                "cv_rules.json",
                "cover_letter_rules.json",
                "companies.json",
                "roles.json",
                "notification_rules.json",
            ):
                path = destination / filename
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["approved"] = False
                if filename == "skills.json":
                    payload["categories"] = {}
                elif filename == "career_strategy.json":
                    payload.update(
                        {
                            "target_roles": [],
                            "priority_domains": [],
                            "objectives": [],
                            "role_tiers": [],
                        }
                    )
                elif filename == "preferences.json":
                    payload["full_time_start"] = None
                path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            return self.get_detail(request.candidate_id)
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise

    def export(self, candidate_id: str) -> dict[str, Any]:
        return self.get_config(candidate_id).model_dump(mode="json")

    @contextmanager
    def lifecycle_read(self, candidate_id: str) -> Iterator[CandidateConfig]:
        with self._write_lock, self._lifecycle_lock(candidate_id):
            yield self.get_config(candidate_id)

    @contextmanager
    def lifecycle_write(self, candidate_id: str) -> Iterator[CandidateConfig]:
        """Fence a candidate filesystem publisher against concurrent erasure."""
        with self._write_lock, self._lifecycle_lock(candidate_id):
            yield self.get_config(candidate_id)

    @contextmanager
    def lifecycle_fence(self, candidate_id: str) -> Iterator[None]:
        """Serialize a complete lifecycle transition without requiring live configuration."""
        with self._write_lock, self._lifecycle_lock(candidate_id):
            yield

    def create_cv_import(self, candidate_id: str, request: CVImportRequest) -> CVImportDraft:
        with self._write_lock, self._lifecycle_lock(candidate_id):
            self.get_config(candidate_id)
            try:
                draft = extract_cv_draft(candidate_id, request)
            except CVImportError as exc:
                raise CandidateUpdateError(str(exc)) from exc
            candidate_directory = self._candidate_directory(candidate_id)
            imports = candidate_directory / ".imports"
            if imports.exists() and (
                imports.is_symlink() or imports.resolve().parent != candidate_directory
            ):
                raise CandidateUpdateError("candidate CV import directory is unsafe")
            imports.mkdir(mode=0o700, exist_ok=True)
            imports.chmod(0o700)
            destination = imports / f"{draft.import_id}.json"
            if destination.is_symlink():
                raise CandidateUpdateError("stored CV import draft path is unsafe")
            if destination.is_file():
                try:
                    stored = CVImportDraft.model_validate_json(
                        destination.read_text(encoding="utf-8")
                    )
                except ValidationError as exc:
                    raise CandidateUpdateError("stored CV import draft is invalid") from exc
                if (
                    stored.candidate_id != candidate_id
                    or stored.source_sha256 != draft.source_sha256
                ):
                    raise CandidateUpdateError("stored CV import draft identity does not match")
                return stored
            temporary = imports / f".{draft.import_id}.{uuid4().hex}.tmp"
            try:
                temporary.write_text(
                    draft.model_dump_json(indent=2) + "\n",
                    encoding="utf-8",
                )
                temporary.chmod(0o600)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
            return draft

    def apply_cv_import(self, candidate_id: str, import_id: str) -> CandidateDetail:
        if re.fullmatch(r"cv_[a-f0-9]{20}", import_id) is None:
            raise CandidateUpdateError("CV import ID is invalid")
        with self._write_lock, self._lifecycle_lock(candidate_id):
            config = self.get_config(candidate_id)
            candidate_directory = self._candidate_directory(candidate_id)
            imports = candidate_directory / ".imports"
            if imports.is_symlink() or imports.resolve().parent != candidate_directory:
                raise CandidateUpdateError("candidate CV import directory is unsafe")
            import_path = imports / f"{import_id}.json"
            if not import_path.is_file() or import_path.is_symlink():
                raise CandidateUpdateError("CV import draft was not found")
            try:
                draft = CVImportDraft.model_validate_json(import_path.read_text(encoding="utf-8"))
            except ValidationError as exc:
                raise CandidateUpdateError("stored CV import draft is invalid") from exc
            if draft.candidate_id != candidate_id:
                raise CandidateUpdateError("CV import draft belongs to another candidate")
            if draft.applied_profile_version is not None:
                return self.get_detail(candidate_id)
            if not draft.education.items and not draft.experience.items:
                raise CandidateUpdateError("CV import contains no structured entries to apply")

            education_by_id = {item.id: item for item in config.education.items}
            experience_by_id = {item.id: item for item in config.experience.items}
            education_conflicts = {
                item.id
                for item in draft.education.items
                if item.id in education_by_id and education_by_id[item.id] != item
            }
            experience_conflicts = {
                item.id
                for item in draft.experience.items
                if item.id in experience_by_id and experience_by_id[item.id] != item
            }
            if education_conflicts or experience_conflicts:
                raise CandidateUpdateError("CV import conflicts with existing stable IDs")
            imported_already = all(
                education_by_id.get(item.id) == item for item in draft.education.items
            ) and all(experience_by_id.get(item.id) == item for item in draft.experience.items)
            if imported_already:
                applied = draft.model_copy(
                    update={"applied_profile_version": config.manifest.profile_version}
                )
                self._write_cv_import(import_path, applied)
                return self.get_detail(candidate_id)

            education = Education(
                items=config.education.items
                + tuple(item for item in draft.education.items if item.id not in education_by_id)
            )
            experience = Experience(
                items=config.experience.items
                + tuple(item for item in draft.experience.items if item.id not in experience_by_id)
            )
            previous_version = config.manifest.profile_version
            next_version = _next_patch_version(previous_version)
            manifest = config.manifest.model_copy(
                update={"profile_version": next_version}, deep=True
            )
            candidate_data = config.model_dump()
            candidate_data.update(
                {"education": education, "experience": experience, "manifest": manifest}
            )
            try:
                updated = CandidateConfig.model_validate(candidate_data)
            except ValidationError as exc:
                raise CandidateUpdateError(str(exc)) from exc
            self._persist_updates(config, updated, ("education", "experience"))
            self._write_cv_import(
                import_path,
                draft.model_copy(update={"applied_profile_version": next_version}),
            )
            return self.get_detail(candidate_id)

    def list_candidates(self) -> tuple[CandidateSummary, ...]:
        if not self._root.is_dir():
            return ()
        summaries: list[CandidateSummary] = []
        for directory in sorted(path for path in self._root.iterdir() if path.is_dir()):
            if not (directory / "profile.yaml").is_file():
                continue
            if self.is_deletion_marked(directory.name):
                continue
            try:
                config = self._loader.load(directory.name)
                if self.is_deletion_marked(directory.name):
                    continue
                readiness = assess_readiness(config)
                automation = (
                    "autonomous"
                    if config.manifest.workflow.automatic_submission_enabled
                    else "disabled"
                )
                summaries.append(
                    CandidateSummary(
                        candidate_id=config.manifest.candidate_id,
                        display_name=config.manifest.display_name,
                        profile_version=config.manifest.profile_version,
                        configuration_status="valid",
                        readiness_status=readiness.status,
                        automation_status=automation,
                    )
                )
            except CandidateConfigError:
                summaries.append(
                    CandidateSummary(
                        candidate_id=directory.name,
                        display_name=directory.name,
                        profile_version=None,
                        configuration_status="invalid",
                        readiness_status="invalid",
                        automation_status="unknown",
                    )
                )
        return tuple(summaries)

    def get_config(self, candidate_id: str) -> CandidateConfig:
        with self._write_lock, self._lifecycle_lock(candidate_id):
            return self._get_config_unlocked(candidate_id)

    def _get_config_unlocked(self, candidate_id: str) -> CandidateConfig:
        self._assert_not_deleted(candidate_id)
        try:
            config = self._loader.load(candidate_id)
        except CandidateConfigError as exc:
            if "not found" in str(exc):
                raise CandidateNotFoundError(str(exc)) from exc
            raise
        self._assert_not_deleted(candidate_id)
        return config

    def get_detail(self, candidate_id: str) -> CandidateDetail:
        config = self.get_config(candidate_id)
        return CandidateDetail(
            candidate_id=candidate_id,
            profile_version=config.manifest.profile_version,
            config=config.model_dump(mode="json"),
            readiness=assess_readiness(config),
        )

    def validate(self, candidate_id: str) -> CandidateValidationReport:
        config = self.get_config(candidate_id)
        readiness = assess_readiness(config)
        return CandidateValidationReport(
            candidate_id=candidate_id,
            status="VALID" if not readiness.issues else "BLOCKING_ERROR",
            profile_version=config.manifest.profile_version,
            issues=tuple(issue.model_dump(mode="json") for issue in readiness.issues),
        )

    def readiness(self, candidate_id: str) -> ReadinessReport:
        return assess_readiness(self.get_config(candidate_id))

    def snapshot(self, candidate_id: str) -> CandidateSnapshot:
        config = self.get_config(candidate_id)
        return build_candidate_snapshot(
            config, candidate_directory=self._candidate_directory(candidate_id)
        )

    def update_section(
        self, candidate_id: str, update: CandidateSectionUpdate
    ) -> CandidateUpdateResult:
        with self._write_lock, self._lifecycle_lock(candidate_id):
            config = self.get_config(candidate_id)
            section_model = _SECTION_MODELS[update.section]
            try:
                section_value = section_model.model_validate(update.data)
            except ValidationError as exc:
                raise CandidateUpdateError(str(exc)) from exc
            previous_version = config.manifest.profile_version
            next_version = _next_patch_version(previous_version)
            data_files = config.manifest.data_files
            if getattr(data_files, update.section) is None:
                default_name = f"{update.section}.json"
                data_files = data_files.model_copy(update={update.section: default_name})
            manifest = config.manifest.model_copy(
                update={"profile_version": next_version, "data_files": data_files}, deep=True
            )
            candidate_data = config.model_dump()
            candidate_data[update.section] = section_value
            candidate_data["manifest"] = manifest
            try:
                updated = CandidateConfig.model_validate(candidate_data)
            except ValidationError as exc:
                raise CandidateUpdateError(str(exc)) from exc
            self._persist_updates(config, updated, (update.section,))
            return CandidateUpdateResult(
                candidate_id=candidate_id,
                previous_version=previous_version,
                profile_version=next_version,
                section=update.section,
                readiness=assess_readiness(updated),
            )

    def is_deletion_marked(self, candidate_id: str) -> bool:
        marker = self._deletion_marker_path(candidate_id)
        if marker.parent.is_symlink() or (marker.parent.exists() and not marker.parent.is_dir()):
            return True
        return marker.exists() or marker.is_symlink()

    def deletion_marker_time(self, candidate_id: str) -> datetime | None:
        marker = self._deletion_marker_path(candidate_id)
        if marker.is_symlink() or not marker.is_file():
            return None
        try:
            return datetime.fromtimestamp(marker.stat().st_mtime, UTC)
        except OSError:
            return None

    def mark_for_deletion(self, candidate_id: str, request_sha256: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{64}", request_sha256):
            raise CandidateUpdateError("candidate deletion request hash is invalid")
        with self._write_lock, self._lifecycle_lock(candidate_id):
            marker = self._deletion_marker_path(candidate_id)
            marker_root = marker.parent
            self._ensure_private_root(marker_root)
            if marker.is_symlink() or (marker.exists() and not marker.is_file()):
                raise CandidateUpdateError("candidate deletion marker is unsafe")
            if marker.is_file():
                try:
                    stored = json.loads(marker.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise CandidateUpdateError("candidate deletion marker is invalid") from exc
                if stored.get("request_sha256") != request_sha256:
                    raise CandidateUpdateError("candidate deletion request conflicts")
                return marker
            self.get_config(candidate_id)
            temporary = marker.with_name(f".{marker.name}.{uuid4().hex}.tmp")
            try:
                temporary.write_text(
                    json.dumps({"request_sha256": request_sha256}, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                temporary.chmod(0o600)
                os.replace(temporary, marker)
            finally:
                temporary.unlink(missing_ok=True)
            return marker

    def purge_deleted_configuration(self, candidate_id: str) -> bool:
        with self._write_lock, self._lifecycle_lock(candidate_id):
            if not self.is_deletion_marked(candidate_id):
                raise CandidateUpdateError("candidate deletion marker is missing")
            directory = self._root / candidate_id
            quarantine_root = self._root / ".deletion_quarantine"
            self._ensure_private_root(quarantine_root)
            quarantine = quarantine_root / candidate_id
            quarantine_present = quarantine.exists() or quarantine.is_symlink()
            directory_present = directory.exists() or directory.is_symlink()
            if quarantine_present and directory_present:
                raise CandidateUpdateError("candidate deletion quarantine conflicts")
            target = quarantine if quarantine_present else directory
            if not (target.exists() or target.is_symlink()):
                return False
            if (
                target.is_symlink()
                or not target.is_dir()
                or target.parent not in {self._root, quarantine_root}
                or target.resolve().parent != target.parent.resolve()
            ):
                raise CandidateUpdateError("candidate deletion path is unsafe")
            self._reject_unsafe_tree(target)
            if target == directory:
                directory.rename(quarantine)
                target = quarantine
            shutil.rmtree(target)
            return True

    def deleted_configuration_absent(self, candidate_id: str) -> bool:
        self._deletion_marker_path(candidate_id)
        directory = self._root / candidate_id
        quarantine = self._root / ".deletion_quarantine" / candidate_id
        return not (directory.exists() or directory.is_symlink()) and not (
            quarantine.exists() or quarantine.is_symlink()
        )

    def configuration_directory(self, candidate_id: str) -> Path:
        return self._candidate_directory(candidate_id)

    def _candidate_directory(self, candidate_id: str) -> Path:
        raw_directory = self._root / candidate_id
        directory = raw_directory.resolve()
        if raw_directory.is_symlink() or directory.parent != self._root or not directory.is_dir():
            raise CandidateNotFoundError(f"candidate not found: {candidate_id}")
        return directory

    def _assert_not_deleted(self, candidate_id: str) -> None:
        if self.is_deletion_marked(candidate_id):
            raise CandidateNotFoundError(f"candidate not found: {candidate_id}")

    def _deletion_marker_path(self, candidate_id: str) -> Path:
        if re.fullmatch(r"[a-z][a-z0-9_]{2,63}", candidate_id) is None:
            raise CandidateNotFoundError(f"candidate not found: {candidate_id}")
        subject = hashlib.sha256(candidate_id.encode()).hexdigest()
        return self._root / ".deletions" / f"{subject}.json"

    @contextmanager
    def _lifecycle_lock(self, candidate_id: str) -> Iterator[None]:
        if re.fullmatch(r"[a-z][a-z0-9_]{2,63}", candidate_id) is None:
            raise CandidateUpdateError("candidate_id must be a safe lowercase identifier")
        lock_root = self._root / ".lifecycle_locks"
        self._ensure_private_root(lock_root)
        subject = hashlib.sha256(candidate_id.encode()).hexdigest()
        held = getattr(self._held_lifecycle_locks, "counts", None)
        if held is None:
            held = {}
            self._held_lifecycle_locks.counts = held
        if held.get(subject, 0):
            held[subject] += 1
            try:
                yield
            finally:
                held[subject] -= 1
            return
        lock_path = lock_root / f"{subject}.lock"
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            flock(descriptor, LOCK_EX)
            held[subject] = 1
            yield
        finally:
            held.pop(subject, None)
            flock(descriptor, LOCK_UN)
            os.close(descriptor)

    def _ensure_private_root(self, path: Path) -> None:
        if path.is_symlink():
            raise CandidateUpdateError("candidate lifecycle path is unsafe")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not path.is_dir() or path.resolve().parent != self._root:
            raise CandidateUpdateError("candidate lifecycle path is unsafe")
        path.chmod(0o700)

    @staticmethod
    def _reject_unsafe_tree(directory: Path) -> None:
        for path in directory.rglob("*"):
            metadata = path.lstat()
            if path.is_symlink():
                raise CandidateUpdateError("candidate deletion tree contains a symlink")
            if path.is_dir():
                continue
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise CandidateUpdateError("candidate deletion tree contains an unsafe file")

    def _persist_updates(
        self,
        previous: CandidateConfig,
        updated: CandidateConfig,
        sections: tuple[CandidateSection, ...],
    ) -> None:
        directory = self._candidate_directory(previous.manifest.candidate_id)
        history = directory / ".history" / previous.manifest.profile_version
        if history.exists():
            raise CandidateUpdateError(f"candidate history already exists: {history.name}")
        history.mkdir(parents=True)
        source_names = ["profile.yaml"] + [
            getattr(previous.manifest.data_files, field_name)
            for field_name in type(previous.manifest.data_files).model_fields
            if getattr(previous.manifest.data_files, field_name) is not None
        ]
        for source_name in source_names:
            shutil.copy2(directory / source_name, history / source_name)

        profile_path = directory / "profile.yaml"
        section_paths: dict[CandidateSection, Path] = {}
        section_temps: dict[CandidateSection, Path] = {}
        for section in sections:
            section_name = getattr(updated.manifest.data_files, section)
            if section_name is None:
                raise CandidateUpdateError("candidate section has no configured source file")
            section_paths[section] = directory / section_name
            section_temps[section] = directory / f".{section_name}.{uuid4().hex}.tmp"
        profile_temp = directory / f".profile.{uuid4().hex}.tmp"
        try:
            for section in sections:
                section_temps[section].write_text(
                    json.dumps(
                        getattr(updated, section).model_dump(mode="json"),
                        indent=2,
                        ensure_ascii=False,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            profile_temp.write_text(
                yaml.safe_dump(
                    updated.manifest.model_dump(mode="json"),
                    sort_keys=False,
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            for section in sections:
                os.replace(section_temps[section], section_paths[section])
            os.replace(profile_temp, profile_path)
        except Exception as exc:
            for section in sections:
                previous_section_name = getattr(previous.manifest.data_files, section)
                if previous_section_name is None:
                    section_paths[section].unlink(missing_ok=True)
                else:
                    shutil.copy2(history / previous_section_name, section_paths[section])
            shutil.copy2(history / "profile.yaml", profile_path)
            for section_temp in section_temps.values():
                section_temp.unlink(missing_ok=True)
            profile_temp.unlink(missing_ok=True)
            raise CandidateUpdateError("candidate update could not be persisted") from exc

    @staticmethod
    def _write_cv_import(path: Path, draft: CVImportDraft) -> None:
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(draft.model_dump_json(indent=2) + "\n", encoding="utf-8")
            temporary.chmod(0o600)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
