from __future__ import annotations

import json
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, ValidationError

from app.candidates.loader import CandidateConfigError, CandidateLoader
from app.candidates.models import (
    ApprovedAnswers,
    Biography,
    CandidateConfig,
    CareerStrategy,
    CompanyRules,
    CoverLetterRules,
    CVRules,
    Education,
    Experience,
    Identity,
    Languages,
    LegalStatus,
    Preferences,
    Projects,
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

    def create(self, request: CandidateCreateRequest) -> CandidateDetail:
        if re.fullmatch(r"[a-z][a-z0-9_]{2,63}", request.candidate_id) is None:
            raise CandidateUpdateError("candidate_id must be a safe lowercase identifier")
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
                    "phone": "UNAPPROVED",
                    "city": "UNAPPROVED",
                    "country_code": "ZZ",
                }
            )
            identity_path.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
            biography_path = destination / "biography.json"
            biography_path.write_text(
                json.dumps(
                    {
                        "summary": "Unapproved onboarding draft; replace with candidate facts.",
                        "highlights": ["Unapproved draft evidence"],
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
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            return self.get_detail(request.candidate_id)
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise

    def export(self, candidate_id: str) -> dict[str, Any]:
        return self.get_config(candidate_id).model_dump(mode="json")

    def list_candidates(self) -> tuple[CandidateSummary, ...]:
        if not self._root.is_dir():
            return ()
        summaries: list[CandidateSummary] = []
        for directory in sorted(path for path in self._root.iterdir() if path.is_dir()):
            if not (directory / "profile.yaml").is_file():
                continue
            try:
                config = self._loader.load(directory.name)
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
        try:
            return self._loader.load(candidate_id)
        except CandidateConfigError as exc:
            if "not found" in str(exc):
                raise CandidateNotFoundError(str(exc)) from exc
            raise

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
        with self._write_lock:
            config = self.get_config(candidate_id)
            section_model = _SECTION_MODELS[update.section]
            try:
                section_value = section_model.model_validate(update.data)
            except ValidationError as exc:
                raise CandidateUpdateError(str(exc)) from exc
            previous_version = config.manifest.profile_version
            next_version = _next_patch_version(previous_version)
            manifest = config.manifest.model_copy(
                update={"profile_version": next_version}, deep=True
            )
            candidate_data = config.model_dump()
            candidate_data[update.section] = section_value
            candidate_data["manifest"] = manifest
            try:
                updated = CandidateConfig.model_validate(candidate_data)
            except ValidationError as exc:
                raise CandidateUpdateError(str(exc)) from exc
            self._persist_update(config, updated, update.section)
            return CandidateUpdateResult(
                candidate_id=candidate_id,
                previous_version=previous_version,
                profile_version=next_version,
                section=update.section,
                readiness=assess_readiness(updated),
            )

    def _candidate_directory(self, candidate_id: str) -> Path:
        directory = (self._root / candidate_id).resolve()
        if directory.parent != self._root or not directory.is_dir():
            raise CandidateNotFoundError(f"candidate not found: {candidate_id}")
        return directory

    def _persist_update(
        self, previous: CandidateConfig, updated: CandidateConfig, section: CandidateSection
    ) -> None:
        directory = self._candidate_directory(previous.manifest.candidate_id)
        history = directory / ".history" / previous.manifest.profile_version
        if history.exists():
            raise CandidateUpdateError(f"candidate history already exists: {history.name}")
        history.mkdir(parents=True)
        source_names = ["profile.yaml"] + [
            getattr(previous.manifest.data_files, field_name)
            for field_name in type(previous.manifest.data_files).model_fields
        ]
        for source_name in source_names:
            shutil.copy2(directory / source_name, history / source_name)

        section_name = getattr(updated.manifest.data_files, section)
        section_path = directory / section_name
        profile_path = directory / "profile.yaml"
        section_temp = directory / f".{section_name}.{uuid4().hex}.tmp"
        profile_temp = directory / f".profile.{uuid4().hex}.tmp"
        try:
            section_temp.write_text(
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
            os.replace(section_temp, section_path)
            os.replace(profile_temp, profile_path)
        except Exception as exc:
            shutil.copy2(history / section_name, section_path)
            shutil.copy2(history / "profile.yaml", profile_path)
            section_temp.unlink(missing_ok=True)
            profile_temp.unlink(missing_ok=True)
            raise CandidateUpdateError("candidate update could not be persisted") from exc
