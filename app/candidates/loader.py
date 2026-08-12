from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

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
    ProfileManifest,
    Projects,
    Publications,
    RoleRules,
    ScoringRules,
    Skills,
)


class CandidateConfigError(ValueError):
    """Raised when candidate configuration cannot be loaded safely."""


_CONFIG_MODELS: dict[str, type[Any]] = {
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


class CandidateLoader:
    def __init__(self, candidates_root: Path) -> None:
        self._root = candidates_root.resolve()

    def load(self, candidate_id: str) -> CandidateConfig:
        candidate_dir = self._safe_candidate_dir(candidate_id)
        manifest = self._read_model(candidate_dir / "profile.yaml", ProfileManifest)
        if manifest.candidate_id != candidate_id:
            raise CandidateConfigError("requested candidate does not match manifest candidate_id")

        loaded: dict[str, Any] = {"manifest": manifest}
        for field_name, model_type in _CONFIG_MODELS.items():
            relative_path = getattr(manifest.data_files, field_name)
            if relative_path is None:
                continue
            config_path = self._safe_config_path(candidate_dir, relative_path)
            loaded[field_name] = self._read_model(config_path, model_type)

        try:
            return CandidateConfig.model_validate(loaded)
        except ValidationError as exc:
            raise CandidateConfigError(str(exc)) from exc

    def _safe_candidate_dir(self, candidate_id: str) -> Path:
        if not candidate_id or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in candidate_id
        ):
            raise CandidateConfigError("candidate_id contains invalid characters")
        raw_candidate_dir = self._root / candidate_id
        candidate_dir = raw_candidate_dir.resolve()
        if raw_candidate_dir.is_symlink() or candidate_dir.parent != self._root:
            raise CandidateConfigError("candidate path escapes candidates root")
        if not candidate_dir.is_dir():
            raise CandidateConfigError(f"candidate not found: {candidate_id}")
        return candidate_dir

    @staticmethod
    def _safe_config_path(candidate_dir: Path, relative_path: str) -> Path:
        raw_path = candidate_dir / relative_path
        path = raw_path.resolve()
        if raw_path.is_symlink() or path.parent != candidate_dir or path.suffix.lower() != ".json":
            raise CandidateConfigError(f"unsafe candidate file path: {relative_path}")
        return path

    @staticmethod
    def _read_model[T](path: Path, model_type: type[T]) -> T:
        try:
            raw = path.read_text(encoding="utf-8")
            data = yaml.safe_load(raw)
            return model_type.model_validate(data)  # type: ignore[attr-defined, no-any-return]
        except (OSError, yaml.YAMLError, ValidationError) as exc:
            raise CandidateConfigError(f"invalid candidate file {path.name}: {exc}") from exc
