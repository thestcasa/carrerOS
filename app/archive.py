from __future__ import annotations

import hashlib
import html
import io
import json
import re
import shutil
import tempfile
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pypdf import PdfReader


class ArchiveExistsError(FileExistsError):
    pass


class ArchiveManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    candidate_id: str
    application_id: UUID
    candidate_profile_version: str | None
    candidate_snapshot_sha256: str
    company: dict[str, str | None]
    job: dict[str, str | None]
    status: str
    created_at: datetime
    submitted_at: datetime | None
    cv: dict[str, str | None]
    cover_letter: dict[str, str | bool | None]
    answers_file: str
    match_score: int | float | None
    validation_status: str
    submission_confirmation: dict[str, str | bool | None]
    agent_version: str
    model_versions: dict[str, str]
    prompt_versions: dict[str, str]
    application_version: int
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
    security_event_log: Any = ()
    error_log: Any = ()
    required_document_kinds: tuple[str, ...] = ("cv",)
    browser_pre_submit_screenshot: bytes | None = None
    browser_final_page_snapshot: bytes | None = None


_PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63606060f80f0001040100c89f17d90000000049454e44ae426082"
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


def _slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:80] or fallback


def _jsonl_bytes(items: Any) -> bytes:
    if not isinstance(items, list):
        return b""
    return b"".join(canonical_json_bytes(item) for item in items)


class ApplicationArchiveBuilder:
    def __init__(self, archives_root: Path) -> None:
        self._root = archives_root.resolve()

    def create(
        self,
        *,
        candidate_id: str,
        application_id: UUID,
        data: ApplicationArchiveData,
        recover_existing: bool = False,
    ) -> Path:
        if not candidate_id or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in candidate_id
        ):
            raise ValueError("candidate_id contains invalid characters")
        job = data.job_snapshot if isinstance(data.job_snapshot, dict) else {}
        company = str(job.get("company") or "unknown-company")
        title = str(job.get("title") or "unknown-role")
        job_id = str(job.get("external_id") or job.get("id") or application_id)
        candidate_directory = self._root / candidate_id
        candidate_root = candidate_directory / str(datetime.now(UTC).year)
        company_directory = candidate_root / _slug(company, "company")
        self._root.mkdir(parents=True, exist_ok=True)
        for path, expected_parent in (
            (candidate_directory, self._root),
            (candidate_root, candidate_directory),
            (company_directory, candidate_root),
        ):
            if path.is_symlink():
                raise ValueError("archive candidate path contains a symlink")
            path.mkdir(exist_ok=True)
            if not path.is_dir() or path.resolve() != path or path.parent != expected_parent:
                raise ValueError("archive candidate path is unsafe")
        final_path = company_directory / f"{_slug(title, 'job')}__{_slug(job_id, 'job-id')}"
        if final_path.exists():
            if recover_existing and self.verify(final_path):
                existing = ArchiveManifest.model_validate_json(
                    (final_path / "manifest.json").read_text(encoding="utf-8")
                )
                if (
                    existing.candidate_id == candidate_id
                    and existing.application_id == application_id
                    and existing.status == "ready_to_submit"
                    and self._matches_expected(final_path, data)
                ):
                    return final_path
            raise ArchiveExistsError(f"archive already exists: {final_path}")

        temp_path = Path(tempfile.mkdtemp(prefix=".building-", dir=candidate_root))
        try:
            hashes: dict[str, str] = {}

            def write(relative: str, content: bytes) -> None:
                path = temp_path / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                hashes[relative] = sha256_bytes(content)

            candidate_bytes = canonical_json_bytes(data.candidate_snapshot)
            write("candidate_snapshot/profile.json", candidate_bytes)
            raw_description = str(job.get("description_raw") or job.get("description") or "")
            normalized_description = str(job.get("description_normalized") or raw_description)
            write(
                "job_post/raw.html",
                (
                    "<!doctype html><html><body><pre>"
                    f"{html.escape(raw_description)}</pre></body></html>\n"
                ).encode(),
            )
            write("job_post/extracted.txt", (raw_description + "\n").encode())
            write(
                "job_post/normalized.json",
                canonical_json_bytes({**job, "description_normalized": normalized_description}),
            )
            write("job_post/screenshot.png", _PNG_1PX)

            scoring = data.scoring_results if isinstance(data.scoring_results, dict) else {}
            write(
                "scoring/classification.json",
                canonical_json_bytes(
                    {
                        "role_category": scoring.get("role_category"),
                        "confidence": scoring.get("classification_confidence"),
                    }
                ),
            )
            write("scoring/score.json", canonical_json_bytes(scoring))
            explanation = (
                scoring.get("explanation")
                or scoring.get("summary")
                or json.dumps(scoring, default=_json_default, sort_keys=True)
            )
            write("scoring/score_explanation.md", (str(explanation) + "\n").encode())
            write("scoring/validation_report.json", canonical_json_bytes(data.validation_report))

            document_hashes: dict[str, str] = {}
            document_templates: dict[str, str] = {}
            references = data.generated_document_references
            if isinstance(references, list):
                for reference in references:
                    if not isinstance(reference, dict):
                        continue
                    kind = str(reference.get("kind") or "")
                    if kind in document_hashes:
                        raise ValueError(f"duplicate rendered document reference: {kind}")
                    storage_uri = reference.get("storage_uri")
                    if not isinstance(storage_uri, str):
                        if kind in data.required_document_kinds:
                            raise ValueError(f"required {kind} source path is missing")
                        continue
                    source = Path(storage_uri)
                    if not source.is_file():
                        if kind in data.required_document_kinds:
                            raise ValueError(f"required {kind} source file is missing")
                        continue
                    if reference.get("content_type") != "application/pdf":
                        raise ValueError(f"required {kind} is not a validated rendered PDF")
                    pdf = source.read_bytes()
                    expected_hash = reference.get("sha256")
                    template_id = reference.get("template_id")
                    template_version = reference.get("template_version")
                    if (
                        not isinstance(expected_hash, str)
                        or not isinstance(template_id, str)
                        or not template_id
                        or not isinstance(template_version, str)
                        or not template_version
                        or sha256_bytes(pdf) != expected_hash
                        or not pdf.startswith(b"%PDF-")
                    ):
                        raise ValueError(f"required {kind} rendered PDF hash is invalid")
                    try:
                        if not PdfReader(io.BytesIO(pdf)).pages:
                            raise ValueError
                    except Exception as exc:
                        raise ValueError(
                            f"required {kind} rendered PDF is structurally invalid"
                        ) from exc
                    if kind == "cv":
                        relative = "submitted_documents/cv_submitted.pdf"
                    elif kind == "cover_letter":
                        relative = "submitted_documents/cover_letter_submitted.pdf"
                    else:
                        continue
                    write(relative, pdf)
                    document_hashes[kind] = hashes[relative]
                    document_templates[kind] = f"{template_id}@{template_version}"
            missing_documents = set(data.required_document_kinds) - set(document_hashes)
            if missing_documents:
                raise ValueError(
                    "required submitted documents are missing: "
                    + ", ".join(sorted(missing_documents))
                )

            questions = (
                [
                    {"question": item.get("question"), "question_key": item.get("question_key")}
                    for item in data.answers
                    if isinstance(item, dict)
                ]
                if isinstance(data.answers, list)
                else []
            )
            write("answers/application_questions.json", canonical_json_bytes(questions))
            write("answers/final_answers.json", canonical_json_bytes(data.answers))
            screenshot = data.browser_pre_submit_screenshot
            final_page_snapshot = data.browser_final_page_snapshot
            if screenshot is None or not screenshot.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("verified browser pre-submit screenshot is required")
            if final_page_snapshot is None:
                raise ValueError("verified browser final-page snapshot is required")
            try:
                final_page_text = final_page_snapshot.decode("utf-8")
            except UnicodeError as exc:
                raise ValueError("verified browser final-page snapshot is invalid") from exc
            if "<html" not in final_page_text.casefold():
                raise ValueError("verified browser final-page snapshot is invalid")
            write("submission/pre_submit_screenshot.png", screenshot)
            write("submission/final_page_snapshot.html", final_page_snapshot)
            write(
                "submission/receipt.json",
                canonical_json_bytes(
                    {
                        "application_id": str(application_id),
                        "status": "ready_to_submit",
                        "confirmation_detected": False,
                        "synthetic_only": True,
                    }
                ),
            )
            write("audit/events.jsonl", _jsonl_bytes(data.event_log))
            write("audit/security_events.jsonl", _jsonl_bytes(data.security_event_log))
            write("audit/errors.jsonl", _jsonl_bytes(data.error_log))
            (temp_path / "correspondence").mkdir(parents=True, exist_ok=True)

            profile_version = None
            if isinstance(data.candidate_snapshot, dict):
                manifest_data = data.candidate_snapshot.get("manifest")
                if isinstance(manifest_data, dict):
                    profile_version = str(manifest_data.get("profile_version") or "") or None
                profile_version = profile_version or (
                    str(data.candidate_snapshot.get("profile_version") or "") or None
                )
            score_value = scoring.get("total_score", scoring.get("score"))
            validation = data.validation_report if isinstance(data.validation_report, dict) else {}
            validation_passed = bool(
                validation.get("documents_valid", validation.get("valid", validation.get("passed")))
            )
            manifest = ArchiveManifest(
                schema_version="2.0",
                candidate_id=candidate_id,
                application_id=application_id,
                candidate_profile_version=profile_version,
                candidate_snapshot_sha256=sha256_bytes(candidate_bytes),
                company={"name": company, "domain": job.get("company_domain")},
                job={
                    "title": title,
                    "classification": scoring.get("role_category"),
                    "external_job_id": str(job.get("external_id") or job_id),
                    "source_url": job.get("source_url"),
                    "application_url": job.get("application_url"),
                },
                status="ready_to_submit",
                created_at=datetime.now(UTC),
                submitted_at=None,
                cv={
                    "template": document_templates.get("cv"),
                    "filename": "cv_submitted.pdf",
                    "sha256": document_hashes.get("cv"),
                },
                cover_letter={
                    "included": "cover_letter" in document_hashes,
                    "filename": "cover_letter_submitted.pdf"
                    if "cover_letter" in document_hashes
                    else None,
                    "sha256": document_hashes.get("cover_letter"),
                },
                answers_file="answers/final_answers.json",
                match_score=score_value if isinstance(score_value, (int, float)) else None,
                validation_status="passed" if validation_passed else "failed",
                submission_confirmation={"detected": False, "confirmation_id": None},
                agent_version="deterministic-fixture-v1",
                model_versions={},
                prompt_versions={},
                application_version=1,
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

    def finalize_confirmed(
        self,
        archive_path: Path,
        *,
        confirmation_reference: str,
        submitted_at: datetime,
        event_log: Any | None = None,
        synthetic_only: bool = True,
        confirmation_screenshot: bytes | None = None,
        final_page_snapshot: bytes | None = None,
    ) -> Path:
        """Create a complete confirmed archive version without mutating the pre-submit archive."""
        raw_source = archive_path.absolute()
        if raw_source.is_symlink() or any(
            parent.is_symlink()
            for parent in raw_source.parents
            if parent != self._root and parent.is_relative_to(self._root)
        ):
            raise ValueError("pre-submit archive path contains a symlink")
        source = raw_source.resolve()
        if not source.is_relative_to(self._root) or not self.verify(source):
            raise ValueError("pre-submit archive is missing, unsafe, or failed verification")
        if not confirmation_reference.strip():
            raise ValueError("confirmation_reference must not be empty")
        if not synthetic_only and (confirmation_screenshot is None or final_page_snapshot is None):
            raise ValueError("controlled confirmation requires screenshot and page evidence")
        original = ArchiveManifest.model_validate_json(
            (source / "manifest.json").read_text(encoding="utf-8")
        )
        expected_source = (
            self._root
            / original.candidate_id
            / str(original.created_at.year)
            / _slug(str(original.company.get("name") or ""), "company")
            / (
                f"{_slug(str(original.job.get('title') or ''), 'job')}__"
                f"{_slug(str(original.job.get('external_job_id') or ''), 'job-id')}"
            )
        ).resolve()
        if source != expected_source:
            raise ValueError("pre-submit archive path does not match its manifest identity")
        destination = source.with_name(f"{source.name}__confirmed_v2")
        if destination.exists():
            if self.verify(destination):
                existing = ArchiveManifest.model_validate_json(
                    (destination / "manifest.json").read_text(encoding="utf-8")
                )
                if (
                    existing.status == "confirmed"
                    and existing.application_id == original.application_id
                    and existing.submission_confirmation.get("confirmation_id")
                    == confirmation_reference
                ):
                    return destination
            raise ArchiveExistsError(f"confirmed archive already exists: {destination}")

        temp_path = Path(tempfile.mkdtemp(prefix=".confirming-", dir=source.parent))
        try:
            shutil.copytree(source, temp_path, dirs_exist_ok=True)
            receipt = {
                "application_id": str(original.application_id),
                "status": "confirmed",
                "confirmation_detected": True,
                "confirmation_reference": confirmation_reference,
                "submitted_at": submitted_at,
                "synthetic_only": synthetic_only,
                "confirmation_screenshot_available": confirmation_screenshot is not None,
            }
            (temp_path / "submission" / "receipt.json").write_bytes(canonical_json_bytes(receipt))
            (temp_path / "submission" / "confirmation.html").write_text(
                "<!doctype html><html><body><p>"
                + (
                    "Synthetic backend confirmation: "
                    if synthetic_only
                    else "Backend confirmation: "
                )
                + f"{html.escape(confirmation_reference)}</p></body></html>\n",
                encoding="utf-8",
            )
            if confirmation_screenshot is not None:
                (temp_path / "submission" / "confirmation_screenshot.png").write_bytes(
                    confirmation_screenshot
                )
            if final_page_snapshot is not None:
                (temp_path / "submission" / "final_page_snapshot.html").write_bytes(
                    final_page_snapshot
                )
            if event_log is not None:
                (temp_path / "audit" / "events.jsonl").write_bytes(_jsonl_bytes(event_log))

            hashes = {
                path.relative_to(temp_path).as_posix(): sha256_bytes(path.read_bytes())
                for path in temp_path.rglob("*")
                if path.is_file() and path.name != "manifest.json"
            }
            confirmed = original.model_copy(
                update={
                    "status": "confirmed",
                    "submitted_at": submitted_at,
                    "submission_confirmation": {
                        "detected": True,
                        "confirmation_id": confirmation_reference,
                    },
                    "application_version": 2,
                    "files": hashes,
                }
            )
            (temp_path / "manifest.json").write_bytes(
                canonical_json_bytes(confirmed.model_dump(mode="json"))
            )
            if not self.verify(temp_path):
                raise ValueError("confirmed archive failed verification")
            temp_path.rename(destination)
        except Exception:
            if temp_path.exists():
                shutil.rmtree(temp_path)
            raise
        return destination

    @staticmethod
    def _matches_expected(archive_path: Path, data: ApplicationArchiveData) -> bool:
        try:
            manifest = ArchiveManifest.model_validate_json(
                (archive_path / "manifest.json").read_text(encoding="utf-8")
            )
            if (
                archive_path / "candidate_snapshot" / "profile.json"
            ).read_bytes() != canonical_json_bytes(data.candidate_snapshot):
                return False
        except (OSError, ValueError, TypeError):
            return False
        try:
            archived_screenshot = (
                archive_path / "submission" / "pre_submit_screenshot.png"
            ).read_bytes()
            archived_final_page = (
                archive_path / "submission" / "final_page_snapshot.html"
            ).read_bytes()
        except OSError:
            return False
        expected: dict[str, str] = {}
        references = data.generated_document_references
        if not isinstance(references, list):
            return not data.required_document_kinds
        for reference in references:
            if not isinstance(reference, dict):
                return False
            kind = reference.get("kind")
            digest = reference.get("sha256")
            if not isinstance(kind, str) or not isinstance(digest, str) or kind in expected:
                return False
            expected[kind] = digest
        return (
            manifest.cv.get("sha256") == expected.get("cv")
            and manifest.cover_letter.get("sha256") == expected.get("cover_letter")
            and data.browser_pre_submit_screenshot is not None
            and data.browser_final_page_snapshot is not None
            and archived_screenshot == data.browser_pre_submit_screenshot
            and archived_final_page == data.browser_final_page_snapshot
        )

    @staticmethod
    def verify(archive_path: Path) -> bool:
        if archive_path.is_symlink() or not archive_path.is_dir():
            return False
        try:
            manifest = ArchiveManifest.model_validate_json(
                (archive_path / "manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return False
        paths = tuple(archive_path.rglob("*"))
        if any(path.is_symlink() for path in paths):
            return False
        actual_files = {
            path.relative_to(archive_path).as_posix()
            for path in paths
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
