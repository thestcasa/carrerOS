from __future__ import annotations

import base64
import binascii
import hashlib
import io
import re
import zipfile
from datetime import date
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader

from app.candidates.models import ClaimFact, Education, EducationItem, Experience, ExperienceItem

MAX_CV_BYTES = 2 * 1024 * 1024
MAX_EXTRACTED_CHARACTERS = 500_000
MAX_CV_LINES = 5_000
MAX_SECTION_ENTRIES = 100
MAX_ENTRY_BULLETS = 20
MAX_ENTRY_FIELDS = 20
MAX_FIELD_CHARACTERS = 500
MAX_PDF_PAGES = 50
MAX_DOCX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
MAX_DOCX_XML_BYTES = 4 * 1024 * 1024


class CVImportError(ValueError):
    pass


class CVImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str = Field(pattern=r"^[^/\\\x00]{1,120}\.(?:txt|pdf|docx)$")
    content_base64: str = Field(min_length=1, max_length=3_000_000)


class CVImportDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    import_id: str = Field(pattern=r"^cv_[a-f0-9]{20}$")
    candidate_id: str
    source_filename: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    education: Education
    experience: Experience
    warnings: tuple[str, ...]
    approval_required: Literal[True] = True
    applied_profile_version: str | None = None


class _ParsedEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fields: tuple[str, ...]
    bullets: tuple[str, ...] = ()


def extract_cv_draft(candidate_id: str, request: CVImportRequest) -> CVImportDraft:
    document = _decode_document(request.content_base64)
    text = _extract_text(request.filename, document)
    source_sha256 = hashlib.sha256(document).hexdigest()
    stable_prefix = source_sha256[:8]
    education_entries, experience_entries = _parse_sections(text)
    education = Education(
        items=tuple(
            _education_item(entry, index, stable_prefix)
            for index, entry in enumerate(education_entries, 1)
        )
    )
    experience = Experience(
        items=tuple(
            _experience_item(entry, index, stable_prefix)
            for index, entry in enumerate(experience_entries, 1)
        )
    )
    warnings: list[str] = [
        "CV extraction is deterministic and may be incomplete; review every field before approval."
    ]
    if not education.items:
        warnings.append("No structured education rows were detected.")
    if not experience.items:
        warnings.append("No structured experience rows were detected.")
    return CVImportDraft(
        import_id=f"cv_{source_sha256[:20]}",
        candidate_id=candidate_id,
        source_filename=Path(request.filename).name,
        source_sha256=source_sha256,
        education=education,
        experience=experience,
        warnings=tuple(warnings),
    )


def _decode_document(value: str) -> bytes:
    try:
        document = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise CVImportError("CV content is not valid base64") from exc
    if not document:
        raise CVImportError("CV document is empty")
    if len(document) > MAX_CV_BYTES:
        raise CVImportError("CV document exceeds the 2 MiB import limit")
    return document


def _extract_text(filename: str, document: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".txt":
        try:
            text = document.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CVImportError("text CV must be valid UTF-8") from exc
    elif suffix == ".pdf":
        text = _extract_pdf_text(document)
    elif suffix == ".docx":
        text = _extract_docx_text(document)
    else:
        raise CVImportError("CV import supports UTF-8 text, PDF, and DOCX files")
    normalized = "\n".join(line.strip() for line in text.splitlines()).strip()
    if len(normalized) > MAX_EXTRACTED_CHARACTERS:
        raise CVImportError("CV extracted text exceeds the safety limit")
    if not normalized:
        raise CVImportError("CV contains no extractable text")
    if len(normalized.splitlines()) > MAX_CV_LINES:
        raise CVImportError("CV exceeds the structured line limit")
    return normalized


def _extract_pdf_text(document: bytes) -> str:
    if not document.startswith(b"%PDF-"):
        raise CVImportError("PDF CV has an invalid file signature")
    try:
        reader = PdfReader(io.BytesIO(document), strict=True)
        if reader.is_encrypted:
            raise CVImportError("encrypted PDF CVs are not supported")
        if not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
            raise CVImportError("PDF CV must contain 1 to 50 pages")
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except CVImportError:
        raise
    except Exception as exc:
        raise CVImportError("PDF CV could not be parsed safely") from exc


def _extract_docx_text(document: bytes) -> str:
    if not document.startswith(b"PK"):
        raise CVImportError("DOCX CV has an invalid file signature")
    try:
        with zipfile.ZipFile(io.BytesIO(document)) as archive:
            entries = archive.infolist()
            if any(
                entry.filename.startswith(("/", "\\")) or ".." in Path(entry.filename).parts
                for entry in entries
            ):
                raise CVImportError("DOCX CV contains an unsafe archive path")
            if sum(entry.file_size for entry in entries) > MAX_DOCX_UNCOMPRESSED_BYTES:
                raise CVImportError("DOCX CV exceeds the uncompressed safety limit")
            try:
                document_entry = archive.getinfo("word/document.xml")
            except KeyError as exc:
                raise CVImportError("DOCX CV is missing its document body") from exc
            if document_entry.file_size > MAX_DOCX_XML_BYTES:
                raise CVImportError("DOCX CV document body exceeds the safety limit")
            xml = archive.read(document_entry)
    except CVImportError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise CVImportError("DOCX CV could not be parsed safely") from exc
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise CVImportError("DOCX CV document XML is invalid") from exc
    paragraphs: list[str] = []
    for paragraph in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        text = "".join(
            node.text or ""
            for node in paragraph.iter(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
            )
        )
        paragraphs.append(text)
    return "\n".join(paragraphs)


def _parse_sections(text: str) -> tuple[tuple[_ParsedEntry, ...], tuple[_ParsedEntry, ...]]:
    sections: dict[str, list[_ParsedEntry]] = {"education": [], "experience": []}
    current_section: str | None = None
    current_fields: tuple[str, ...] | None = None
    current_bullets: list[str] = []

    def finish_entry() -> None:
        nonlocal current_fields, current_bullets
        if current_section is not None and current_fields is not None:
            if len(sections[current_section]) >= MAX_SECTION_ENTRIES:
                raise CVImportError(f"CV {current_section} exceeds the entry limit")
            sections[current_section].append(
                _ParsedEntry(fields=current_fields, bullets=tuple(current_bullets))
            )
        current_fields = None
        current_bullets = []

    for line in text.splitlines():
        heading = line.strip().lower().rstrip(":")
        if heading in sections:
            finish_entry()
            current_section = heading
            continue
        if current_section is None or not line.strip():
            continue
        if line.lstrip().startswith(("-", "•")):
            if current_fields is not None:
                bullet = line.lstrip()[1:].strip()
                if bullet:
                    if len(bullet) > MAX_FIELD_CHARACTERS:
                        raise CVImportError("CV bullet exceeds the field length limit")
                    if len(current_bullets) >= MAX_ENTRY_BULLETS:
                        raise CVImportError("CV entry exceeds the bullet limit")
                    current_bullets.append(bullet)
            continue
        fields = tuple(part.strip() for part in line.split("|") if part.strip())
        if len(fields) >= 6:
            if len(fields) > MAX_ENTRY_FIELDS:
                raise CVImportError("CV entry exceeds the field count limit")
            if any(len(field) > MAX_FIELD_CHARACTERS for field in fields):
                raise CVImportError("CV entry exceeds the field length limit")
            finish_entry()
            current_fields = fields
    finish_entry()
    return tuple(sections["education"]), tuple(sections["experience"])


def _education_item(entry: _ParsedEntry, index: int, stable_prefix: str) -> EducationItem:
    institution, qualification, field, location, start, end = entry.fields[:6]
    return EducationItem(
        id=f"cv_{stable_prefix}_edu_{index}",
        institution=institution,
        qualification=qualification,
        field_of_study=field,
        location=location,
        start_date=_parse_month(start),
        end_date=_parse_month(end),
        completed=end.lower() not in {"present", "current"},
        approved=False,
        archived=False,
    )


def _experience_item(entry: _ParsedEntry, index: int, stable_prefix: str) -> ExperienceItem:
    organization, title, location, start, end, *skills = entry.fields
    current = end.lower() in {"present", "current"}
    achievements = tuple(
        ClaimFact(
            id=f"cv_{stable_prefix}_exp_{index}_claim_{bullet_index}",
            statement=bullet,
            verified=False,
            publicly_usable=False,
            confidentiality="restricted",
            approved=False,
        )
        for bullet_index, bullet in enumerate(entry.bullets, 1)
    )
    return ExperienceItem(
        id=f"cv_{stable_prefix}_exp_{index}",
        organization=organization,
        title=title,
        location=location,
        start_date=_parse_month(start),
        end_date=None if current else _parse_month(end),
        current=current,
        achievements=achievements,
        skills=tuple(skill for value in skills for skill in _split_skills(value)),
        confidentiality="restricted",
        approved=False,
        archived=False,
    )


def _parse_month(value: str) -> date:
    match = re.fullmatch(r"(\d{4})-(\d{2})(?:-\d{2})?", value.strip())
    if match is None:
        raise CVImportError(f"CV date must use YYYY-MM: {value}")
    try:
        return date(int(match.group(1)), int(match.group(2)), 1)
    except ValueError as exc:
        raise CVImportError(f"CV date is invalid: {value}") from exc


def _split_skills(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in re.split(r"[,;/]", value) if item.strip())
