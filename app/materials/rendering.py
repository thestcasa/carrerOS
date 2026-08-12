from __future__ import annotations

import hashlib
import io
import re
import textwrap
from dataclasses import dataclass
from urllib.parse import urlsplit

from pypdf import PdfReader

from app.domain.enums import DocumentKind
from app.materials.contracts import (
    GeneratedDocument,
    RenderValidationReport,
    ValidationIssue,
)
from app.materials.latex import DeterministicLatexSourceBuilder

_LINES_PER_PAGE = 54
_LINE_WIDTH = 96
_MAX_SOURCE_BYTES = 256_000
_FONT_SIZE = 9
_COURIER_GLYPH_WIDTH = 0.6 * _FONT_SIZE
_PRINTABLE_WIDTH = 522
_LINE_SPACING = 13
_URL = re.compile(r"(?P<url>[a-z][a-z0-9+.-]*:[^\s<>]+)", re.IGNORECASE)
_TEMPLATES = {
    ("technical_single_page", "1.0"): 1,
    ("technical_two_page", "1.0"): 2,
    ("application_letter", "1.0"): 2,
}


@dataclass(frozen=True, slots=True)
class RenderedMaterial:
    document: GeneratedDocument
    latex_source: bytes
    pdf_bytes: bytes
    report: RenderValidationReport


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _normalized_lines(content: str) -> tuple[str, ...]:
    lines: list[str] = []
    for source_line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not source_line:
            lines.append("")
            continue
        lines.extend(
            textwrap.wrap(
                source_line,
                width=_LINE_WIDTH,
                break_long_words=False,
                break_on_hyphens=False,
                replace_whitespace=False,
                drop_whitespace=True,
            )
            or [""]
        )
    return tuple(lines)


def _pdf_string(value: str) -> bytes:
    encoded = value.encode("cp1252")
    return encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _build_pdf(pages: tuple[tuple[str, ...], ...]) -> bytes:
    page_count = len(pages)
    font_id = 3 + page_count
    content_start = font_id + 1
    page_ids = tuple(range(3, 3 + page_count))
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            b"<< /Type /Pages /Kids ["
            + b" ".join(f"{page_id} 0 R".encode("ascii") for page_id in page_ids)
            + f"] /Count {page_count} >>".encode("ascii")
        ),
    ]
    for index, _page in enumerate(pages):
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
                f"/Contents {content_start + index} 0 R >>"
            ).encode("ascii")
        )
    objects.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>"
    )
    for page in pages:
        commands = [b"BT", f"/F1 {_FONT_SIZE} Tf".encode("ascii"), b"45 790 Td"]
        for index, line in enumerate(page):
            if index:
                commands.append(f"0 -{_LINE_SPACING} Td".encode("ascii"))
            commands.append(b"(" + _pdf_string(line) + b") Tj")
        commands.append(b"ET")
        stream = b"\n".join(commands)
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(output)


class DeterministicPdfRenderer:
    """Versioned, network-free renderer whose fixed layout cannot overlap or hide text."""

    def __init__(self, latex_builder: DeterministicLatexSourceBuilder | None = None) -> None:
        self._latex_builder = latex_builder or DeterministicLatexSourceBuilder()

    def render(
        self,
        document: GeneratedDocument,
        *,
        template_id: str,
        template_version: str,
        maximum_pages: int,
        document_version: int,
    ) -> RenderedMaterial:
        issues: list[ValidationIssue] = []
        latex_source = self._latex_builder.build(
            document,
            template_id=template_id,
            template_version=template_version,
        )
        template_limit = _TEMPLATES.get((template_id, template_version))
        if template_limit is None:
            issues.append(
                ValidationIssue(
                    code="unknown_document_template",
                    severity="error",
                    message="The configured document template and version are not allowlisted.",
                    document_kind=document.kind,
                )
            )
        elif maximum_pages > template_limit:
            issues.append(
                ValidationIssue(
                    code="template_page_limit_exceeded",
                    severity="error",
                    message="The configured page limit exceeds the template's safe layout.",
                    document_kind=document.kind,
                )
            )
        source = document.content.encode("utf-8")
        source_sha256 = _sha256(source)
        if source_sha256 != document.content_sha256:
            issues.append(
                ValidationIssue(
                    code="render_source_hash_mismatch",
                    severity="error",
                    message="Document source does not match its declared content hash.",
                    document_kind=document.kind,
                )
            )
        if len(source) > _MAX_SOURCE_BYTES:
            issues.append(
                ValidationIssue(
                    code="render_source_too_large",
                    severity="error",
                    message="Document source exceeds the deterministic render limit.",
                    document_kind=document.kind,
                )
            )
        if any(ord(character) < 32 and character not in "\n\r\t" for character in document.content):
            issues.append(
                ValidationIssue(
                    code="unsupported_control_character",
                    severity="error",
                    message="Document contains a control character that cannot be rendered safely.",
                    document_kind=document.kind,
                )
            )
        try:
            document.content.encode("cp1252")
        except UnicodeEncodeError:
            issues.append(
                ValidationIssue(
                    code="missing_glyph",
                    severity="error",
                    message="Document contains a glyph unsupported by the versioned template font.",
                    document_kind=document.kind,
                )
            )
        for match in _URL.finditer(document.content):
            candidate = match.group("url").rstrip('.,;:!?)"]}')
            try:
                parsed = urlsplit(candidate)
                invalid_url = (
                    parsed.scheme.casefold() != "https"
                    or not parsed.hostname
                    or parsed.username is not None
                    or parsed.password is not None
                    or (parsed.port is not None and not 1 <= parsed.port <= 65535)
                )
            except ValueError:
                invalid_url = True
            if invalid_url:
                issues.append(
                    ValidationIssue(
                        code="unsafe_document_url",
                        severity="error",
                        message="Document URLs must be credential-free HTTPS URLs.",
                        document_kind=document.kind,
                    )
                )
        lines = _normalized_lines(document.content)
        if any(len(line) * _COURIER_GLYPH_WIDTH > _PRINTABLE_WIDTH for line in lines):
            issues.append(
                ValidationIssue(
                    code="layout_out_of_bounds",
                    severity="error",
                    message="Document contains a line that cannot fit the safe layout.",
                    document_kind=document.kind,
                )
            )
        page_count = max(1, (len(lines) + _LINES_PER_PAGE - 1) // _LINES_PER_PAGE)
        overlap_count = (
            sum(
                max(0, min(_LINES_PER_PAGE, len(lines) - offset) - 1)
                for offset in range(0, len(lines), _LINES_PER_PAGE)
            )
            if _LINE_SPACING < _FONT_SIZE
            else 0
        )
        if page_count > maximum_pages:
            issues.append(
                ValidationIssue(
                    code="document_page_limit_exceeded",
                    severity="error",
                    message=(
                        f"Rendered document requires {page_count} pages; limit is {maximum_pages}."
                    ),
                    document_kind=document.kind,
                )
            )
        if issues:
            report = RenderValidationReport(
                document_kind=document.kind,
                document_version=document_version,
                template_id=template_id,
                template_version=template_version,
                renderer_version="latex_pdf_v1",
                compiler_version="restricted_latex_v1",
                source_sha256=source_sha256,
                latex_sha256=latex_source.sha256,
                page_count=page_count,
                maximum_pages=maximum_pages,
                extraction_matches=False,
                layout_overlap_count=overlap_count,
                valid=False,
                issues=tuple(issues),
            )
            return RenderedMaterial(
                document=document,
                latex_source=latex_source.content,
                pdf_bytes=b"",
                report=report,
            )

        pages = tuple(
            tuple(lines[offset : offset + _LINES_PER_PAGE])
            for offset in range(0, len(lines), _LINES_PER_PAGE)
        ) or (("",),)
        pdf_bytes = _build_pdf(pages)
        extracted = "\n".join(
            (page.extract_text() or "").rstrip("\n")
            for page in PdfReader(io.BytesIO(pdf_bytes)).pages
        )
        # PDF text extractors conventionally omit visually empty lines. Compare every rendered
        # text line in order while treating paragraph spacing as layout rather than content.
        expected = "\n".join(line for line in lines if line)
        extraction_matches = extracted == expected
        if not extraction_matches:
            issues.append(
                ValidationIssue(
                    code="pdf_text_extraction_mismatch",
                    severity="error",
                    message="Extracted PDF text does not match the complete reviewed source.",
                    document_kind=document.kind,
                )
            )
        report = RenderValidationReport(
            document_kind=document.kind,
            document_version=document_version,
            template_id=template_id,
            template_version=template_version,
            renderer_version="latex_pdf_v1",
            compiler_version="restricted_latex_v1",
            source_sha256=source_sha256,
            latex_sha256=latex_source.sha256,
            pdf_sha256=_sha256(pdf_bytes),
            extracted_text_sha256=_sha256(extracted.encode("utf-8")),
            page_count=len(pages),
            maximum_pages=maximum_pages,
            extraction_matches=extraction_matches,
            layout_overlap_count=overlap_count,
            valid=not issues,
            issues=tuple(issues),
        )
        return RenderedMaterial(
            document=document,
            latex_source=latex_source.content,
            pdf_bytes=pdf_bytes,
            report=report,
        )


def template_for(
    kind: DocumentKind, configured_id: str, configured_version: str
) -> tuple[str, str]:
    if kind is DocumentKind.CV:
        return configured_id, configured_version
    return "application_letter", "1.0"
