from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BrowserContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FieldKind(StrEnum):
    TEXT = "text"
    EMAIL = "email"
    TEL = "tel"
    TEXTAREA = "textarea"
    SELECT = "select"
    CHECKBOX = "checkbox"
    FILE = "file"
    CAPTCHA = "captcha"
    OTP = "otp"
    SUBMIT = "submit"


class HumanActionReason(StrEnum):
    CAPTCHA = "captcha"
    OTP = "otp"
    NOVEL_REQUIRED_FIELD = "novel_required_field"


class FormField(BrowserContract):
    field_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: FieldKind
    required: bool = False
    options: tuple[str, ...] = ()
    value: str | bool | None = None

    @model_validator(mode="after")
    def validate_options(self) -> FormField:
        if self.kind == FieldKind.SELECT and not self.options:
            raise ValueError("select fields require options")
        return self


class SyntheticForm(BrowserContract):
    form_id: str = Field(min_length=1)
    source_url: str = Field(pattern=r"^https://synthetic\.invalid(?:/|$)")
    fields: tuple[FormField, ...]

    @model_validator(mode="after")
    def unique_fields(self) -> SyntheticForm:
        field_ids = [field.field_id for field in self.fields]
        if len(field_ids) != len(set(field_ids)):
            raise ValueError("field IDs must be unique")
        return self


class UploadArtifact(BrowserContract):
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    path: Path
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class DryRunRequest(BrowserContract):
    application_id: UUID
    candidate_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    session_id: UUID
    form: SyntheticForm
    answers: dict[str, str | bool]
    uploads: tuple[UploadArtifact, ...] = ()
    allowed_upload_sha256: frozenset[str] = frozenset()


class MappedField(BrowserContract):
    field_id: str
    field_key: str
    kind: FieldKind
    value: str | bool


class HumanActionResult(BrowserContract):
    reason: HumanActionReason
    field_id: str
    message: str
    resumable: bool = True


class FinalPageSnapshot(BrowserContract):
    source_url: str
    values: tuple[MappedField, ...]
    upload_hashes: tuple[str, ...]
    final_submit_present: bool
    final_submit_clicked: Literal[False] = False


class DryRunResult(BrowserContract):
    application_id: UUID
    candidate_id: str
    session_id: UUID
    session_directory: Path
    screenshot_path: Path
    final_page_snapshot_path: Path
    mapped_fields: tuple[MappedField, ...]
    human_actions: tuple[HumanActionResult, ...]
    final_page: FinalPageSnapshot
    ready_for_human_review: bool
    submitted: Literal[False] = False


class PlaywrightDryRunRequest(BrowserContract):
    application_id: UUID
    candidate_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    session_id: UUID
    fixture_url: str = Field(pattern=r"^http://(?:127\.0\.0\.1|localhost):[0-9]+(?:/|$)")
    answers: dict[str, str | bool]
    uploads: tuple[UploadArtifact, ...] = ()
    allowed_upload_sha256: frozenset[str] = frozenset()

    @model_validator(mode="after")
    def validate_field_keys(self) -> PlaywrightDryRunRequest:
        unsafe_keys = set(self.answers) - {
            key
            for key in self.answers
            if key
            and len(key) <= 64
            and key[0].isalpha()
            and key[0].isascii()
            and all(
                character.isascii() and (character.isalnum() or character == "_")
                for character in key
            )
        }
        if unsafe_keys:
            raise ValueError("answer field keys must be safe synthetic fixture identifiers")
        upload_keys = [upload.field_key for upload in self.uploads]
        if len(upload_keys) != len(set(upload_keys)):
            raise ValueError("upload field keys must be unique")
        return self


class PlaywrightDryRunResult(BrowserContract):
    application_id: UUID
    candidate_id: str
    session_id: UUID
    fixture_url: str
    session_directory: Path
    persistent_profile_directory: Path
    screenshot_path: Path
    final_page_snapshot_path: Path
    mapped_values: dict[str, str | bool]
    upload_hashes: tuple[str, ...]
    human_action: Literal["captcha", "otp"] | None
    final_submit_present: bool
    final_submit_clicked: Literal[False] = False
    allowed_network_requests: int = Field(ge=0)
    blocked_network_requests: int = Field(ge=0)
    ready_for_human_review: bool
