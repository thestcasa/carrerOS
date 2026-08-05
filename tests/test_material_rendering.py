from __future__ import annotations

import hashlib
import io

from pypdf import PdfReader

from app.domain.enums import DocumentKind
from app.materials.contracts import Claim, GeneratedDocument
from app.materials.rendering import DeterministicPdfRenderer, RenderedMaterial


def _document(content: str) -> GeneratedDocument:
    return GeneratedDocument(
        kind=DocumentKind.CV,
        company="Fictional Systems Ltd",
        content=content,
        claims=(Claim(text="Fictional evidence", evidence_ids=("fact_one",)),),
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
    )


def _render(content: str, *, maximum_pages: int = 2) -> RenderedMaterial:
    return DeterministicPdfRenderer().render(
        _document(content),
        template_id="technical_two_page",
        template_version="1.0",
        maximum_pages=maximum_pages,
        document_version=1,
    )


def test_pdf_render_is_deterministic_and_preserves_complete_text() -> None:
    content = (
        "CV — Engineer at Fictional Systems Ltd\n\n"
        "Fictional evidence with a € budget and an allowlisted URL.\n"
        "https://careers.fictional.invalid/jobs/123"
    )

    first = _render(content)
    second = _render(content)

    assert first.report.valid
    assert first.pdf_bytes == second.pdf_bytes
    assert first.report.pdf_sha256 == hashlib.sha256(first.pdf_bytes).hexdigest()
    extracted = "\n".join(
        (page.extract_text() or "").rstrip("\n")
        for page in PdfReader(io.BytesIO(first.pdf_bytes)).pages
    )
    assert "Fictional evidence with a € budget" in extracted
    assert "https://careers.fictional.invalid/jobs/123" in extracted
    assert first.report.extraction_matches
    assert first.report.layout_overlap_count == 0


def test_long_document_paginates_without_silent_truncation() -> None:
    content = "\n".join(f"Fictional evidence line {index:03d}" for index in range(80))

    rendered = _render(content)

    assert rendered.report.valid
    assert rendered.report.page_count == 2
    extracted = "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(rendered.pdf_bytes)).pages
    )
    assert "Fictional evidence line 000" in extracted
    assert "Fictional evidence line 079" in extracted


def test_fixed_width_layout_keeps_wide_glyphs_inside_page_bounds() -> None:
    rendered = _render("W " * 48)

    assert rendered.report.valid
    assert rendered.report.layout_overlap_count == 0
    assert not rendered.report.issues


def test_page_limit_glyph_url_and_template_failures_are_blocking() -> None:
    too_long = _render("\n".join(f"line {index}" for index in range(80)), maximum_pages=1)
    missing_glyph = _render("Fictional evidence 🧪")
    unsafe_url = _render("Fictional evidence http://careers.fictional.invalid/job")
    dangerous_url = _render("Fictional evidence javascript:alert(1)")
    alternate_script_url = _render("Fictional evidence vbscript:msgbox(1)")
    malformed_url = _render("Fictional evidence https://[broken")
    invalid_port = _render("Fictional evidence https://example.invalid:bad")
    ftp_url = _render("Fictional evidence ftp://example.invalid/file")
    unknown_template = DeterministicPdfRenderer().render(
        _document("Fictional evidence"),
        template_id="../../candidate",
        template_version="1.0",
        maximum_pages=1,
        document_version=1,
    )

    assert not too_long.report.valid and not too_long.pdf_bytes
    assert not missing_glyph.report.valid and not missing_glyph.pdf_bytes
    assert not unsafe_url.report.valid and not unsafe_url.pdf_bytes
    assert not dangerous_url.report.valid and not dangerous_url.pdf_bytes
    assert not alternate_script_url.report.valid and not alternate_script_url.pdf_bytes
    assert not malformed_url.report.valid and not malformed_url.pdf_bytes
    assert not invalid_port.report.valid and not invalid_port.pdf_bytes
    assert not ftp_url.report.valid and not ftp_url.pdf_bytes
    assert not unknown_template.report.valid and not unknown_template.pdf_bytes
    assert {issue.code for issue in too_long.report.issues} == {"document_page_limit_exceeded"}
    assert {issue.code for issue in missing_glyph.report.issues} == {"missing_glyph"}
    assert {issue.code for issue in unsafe_url.report.issues} == {"unsafe_document_url"}
    assert {issue.code for issue in dangerous_url.report.issues} == {"unsafe_document_url"}
    assert {issue.code for issue in alternate_script_url.report.issues} == {"unsafe_document_url"}
    assert {issue.code for issue in malformed_url.report.issues} == {"unsafe_document_url"}
    assert {issue.code for issue in invalid_port.report.issues} == {"unsafe_document_url"}
    assert {issue.code for issue in ftp_url.report.issues} == {"unsafe_document_url"}
    assert {issue.code for issue in unknown_template.report.issues} == {"unknown_document_template"}


def test_renderer_rejects_a_false_declared_source_hash() -> None:
    document = _document("Fictional evidence").model_copy(update={"content_sha256": "0" * 64})

    rendered = DeterministicPdfRenderer().render(
        document,
        template_id="technical_single_page",
        template_version="1.0",
        maximum_pages=1,
        document_version=1,
    )

    assert not rendered.report.valid
    assert rendered.report.source_sha256 == hashlib.sha256(document.content.encode()).hexdigest()
    assert {issue.code for issue in rendered.report.issues} == {"render_source_hash_mismatch"}
