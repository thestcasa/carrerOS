from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.archive import ApplicationArchiveBuilder, ApplicationArchiveData, ArchiveExistsError
from app.domain.enums import DocumentKind
from app.materials.contracts import ApprovedFact, GenerationRequest, JobTarget
from app.materials.generation import DeterministicMaterialGenerator
from app.materials.rendering import DeterministicPdfRenderer


def _rendered_cv(path: Path) -> tuple[Path, str]:
    request = GenerationRequest(
        candidate_id="candidate_alpha",
        application_id=uuid4(),
        target=JobTarget(company="Fictional Company", title="Engineer"),
        requested_documents=(DocumentKind.CV,),
        approved_facts=(
            ApprovedFact(
                fact_id="fictional_fact",
                text="Built a deterministic fictional system.",
                source_path="experience.items[0]",
            ),
        ),
    )
    document = DeterministicMaterialGenerator().generate(request).documents[0]
    rendered = DeterministicPdfRenderer().render(
        document,
        template_id="technical_single_page",
        template_version="1.0",
        maximum_pages=1,
        document_version=1,
    )
    assert rendered.report.valid and rendered.report.pdf_sha256
    path.write_bytes(rendered.pdf_bytes)
    return path, rendered.report.pdf_sha256


def test_archive_hashes_detect_mutation_and_archive_cannot_be_overwritten(tmp_path: Path) -> None:
    builder = ApplicationArchiveBuilder(tmp_path / "archives")
    application_id = uuid4()
    cv_source, cv_sha256 = _rendered_cv(tmp_path / "fictional-cv.pdf")
    data = ApplicationArchiveData(
        candidate_snapshot={"candidate_id": "candidate_alpha", "version": 1},
        job_snapshot={"job_id": "fictional-job-1"},
        scoring_results={"score": 90},
        generated_document_references=[
            {
                "kind": "cv",
                "sha256": cv_sha256,
                "storage_uri": str(cv_source),
                "content_type": "application/pdf",
                "template_id": "technical_single_page",
                "template_version": "1.0",
            }
        ],
        answers=[{"key": "authorization", "answer": "Yes", "supported": True}],
        validation_report={"passed": True},
        event_log=[{"event": "review_passed"}],
    )

    archive_path = builder.create(
        candidate_id="candidate_alpha", application_id=application_id, data=data
    )

    archived_cv = (archive_path / "submitted_documents" / "cv_submitted.pdf").read_bytes()
    assert archived_cv == cv_source.read_bytes()
    assert builder.verify(archive_path) is True
    manifest = json.loads((archive_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cv"]["sha256"] == cv_sha256
    assert manifest["cv"]["template"] == "technical_single_page@1.0"
    assert {
        "candidate_snapshot/profile.json",
        "job_post/raw.html",
        "job_post/extracted.txt",
        "job_post/normalized.json",
        "job_post/screenshot.png",
        "scoring/classification.json",
        "scoring/score.json",
        "scoring/score_explanation.md",
        "scoring/validation_report.json",
        "answers/application_questions.json",
        "answers/final_answers.json",
        "submission/pre_submit_screenshot.png",
        "submission/final_page_snapshot.html",
        "submission/receipt.json",
        "audit/events.jsonl",
        "audit/security_events.jsonl",
        "audit/errors.jsonl",
    }.issubset(manifest["files"])
    with pytest.raises(ArchiveExistsError):
        builder.create(candidate_id="candidate_alpha", application_id=application_id, data=data)
    assert (
        builder.create(
            candidate_id="candidate_alpha",
            application_id=application_id,
            data=data,
            recover_existing=True,
        )
        == archive_path
    )

    (archive_path / "answers" / "final_answers.json").write_text("[]\n", encoding="utf-8")
    assert builder.verify(archive_path) is False


def test_confirmed_archive_is_copy_on_write_and_contains_final_receipt(tmp_path: Path) -> None:
    builder = ApplicationArchiveBuilder(tmp_path / "archives")
    application_id = UUID("00000000-0000-0000-0000-000000000002")
    source = builder.create(
        candidate_id="candidate_alpha",
        application_id=application_id,
        data=ApplicationArchiveData(
            candidate_snapshot={"profile_version": "1.0.0"},
            job_snapshot={"company": "Example Corp", "title": "Engineer", "id": "job-2"},
            scoring_results={"total_score": 90},
            generated_document_references=[],
            answers=[],
            validation_report={"valid": True},
            event_log=[],
            required_document_kinds=(),
        ),
    )
    original_receipt = (source / "submission" / "receipt.json").read_bytes()

    confirmed = builder.finalize_confirmed(
        source,
        confirmation_reference="synthetic-confirmation-2",
        submitted_at=datetime(2026, 8, 5, 10, tzinfo=UTC),
        event_log=[{"event_type": "SUBMISSION_CONFIRMED"}],
    )

    assert confirmed != source
    assert (source / "submission" / "receipt.json").read_bytes() == original_receipt
    assert builder.verify(source)
    assert builder.verify(confirmed)
    receipt = json.loads((confirmed / "submission" / "receipt.json").read_text())
    manifest = json.loads((confirmed / "manifest.json").read_text())
    assert receipt["status"] == "confirmed"
    assert receipt["confirmation_detected"] is True
    assert manifest["status"] == "confirmed"
    assert manifest["application_version"] == 2
    assert (confirmed / "submission" / "confirmation.html").is_file()
    assert (confirmed / "submission" / "confirmation_screenshot.png").is_file()
    assert (
        builder.finalize_confirmed(
            source,
            confirmation_reference="synthetic-confirmation-2",
            submitted_at=datetime(2026, 8, 5, 10, tzinfo=UTC),
        )
        == confirmed
    )


def test_archive_fails_closed_when_exact_required_document_is_missing(tmp_path: Path) -> None:
    builder = ApplicationArchiveBuilder(tmp_path / "archives")
    with pytest.raises(ValueError, match="required cv source file is missing"):
        builder.create(
            candidate_id="candidate_alpha",
            application_id=UUID("00000000-0000-0000-0000-000000000003"),
            data=ApplicationArchiveData(
                candidate_snapshot={},
                job_snapshot={"company": "Example Corp", "title": "Engineer"},
                scoring_results={},
                generated_document_references=[
                    {"kind": "cv", "storage_uri": str(tmp_path / "missing-cv.txt")}
                ],
                answers=[],
                validation_report={"valid": True},
                event_log=[],
            ),
        )


def test_archive_rejects_a_rendered_pdf_hash_mismatch(tmp_path: Path) -> None:
    cv_source, _digest = _rendered_cv(tmp_path / "fictional-cv.pdf")
    with pytest.raises(ValueError, match="rendered PDF hash is invalid"):
        ApplicationArchiveBuilder(tmp_path / "archives").create(
            candidate_id="candidate_alpha",
            application_id=UUID("00000000-0000-0000-0000-000000000004"),
            data=ApplicationArchiveData(
                candidate_snapshot={},
                job_snapshot={"company": "Example Corp", "title": "Engineer"},
                scoring_results={},
                generated_document_references=[
                    {
                        "kind": "cv",
                        "storage_uri": str(cv_source),
                        "sha256": "0" * 64,
                        "content_type": "application/pdf",
                        "template_id": "technical_single_page",
                        "template_version": "1.0",
                    }
                ],
                answers=[],
                validation_report={"valid": True},
                event_log=[],
            ),
        )


def test_archive_job_identity_is_slugged_and_cannot_escape_root(tmp_path: Path) -> None:
    root = tmp_path / "archives"
    archive = ApplicationArchiveBuilder(root).create(
        candidate_id="candidate_alpha",
        application_id=UUID("00000000-0000-0000-0000-000000000005"),
        data=ApplicationArchiveData(
            candidate_snapshot={},
            job_snapshot={
                "company": "../../outside-company",
                "title": "../outside-role",
                "external_id": "../../outside-job",
            },
            scoring_results={},
            generated_document_references=[],
            answers=[],
            validation_report={"valid": True},
            event_log=[],
            required_document_kinds=(),
        ),
    )

    assert archive.resolve().is_relative_to(root.resolve())
    assert ".." not in archive.relative_to(root).parts


def test_archive_rejects_duplicate_document_versions(tmp_path: Path) -> None:
    cv_source, cv_sha256 = _rendered_cv(tmp_path / "fictional-cv.pdf")
    reference = {
        "kind": "cv",
        "sha256": cv_sha256,
        "storage_uri": str(cv_source),
        "content_type": "application/pdf",
        "template_id": "technical_single_page",
        "template_version": "1.0",
    }

    with pytest.raises(ValueError, match="duplicate rendered document reference"):
        ApplicationArchiveBuilder(tmp_path / "archives").create(
            candidate_id="candidate_alpha",
            application_id=UUID("00000000-0000-0000-0000-000000000006"),
            data=ApplicationArchiveData(
                candidate_snapshot={},
                job_snapshot={"company": "Example Corp", "title": "Engineer"},
                scoring_results={},
                generated_document_references=[reference, reference],
                answers=[],
                validation_report={"valid": True},
                event_log=[],
            ),
        )


def test_archive_verification_rejects_symlinked_content(tmp_path: Path) -> None:
    builder = ApplicationArchiveBuilder(tmp_path / "archives")
    cv_source, cv_sha256 = _rendered_cv(tmp_path / "fictional-cv.pdf")
    archive = builder.create(
        candidate_id="candidate_alpha",
        application_id=UUID("00000000-0000-0000-0000-000000000007"),
        data=ApplicationArchiveData(
            candidate_snapshot={},
            job_snapshot={"company": "Example Corp", "title": "Engineer"},
            scoring_results={},
            generated_document_references=[
                {
                    "kind": "cv",
                    "sha256": cv_sha256,
                    "storage_uri": str(cv_source),
                    "content_type": "application/pdf",
                    "template_id": "technical_single_page",
                    "template_version": "1.0",
                }
            ],
            answers=[],
            validation_report={"valid": True},
            event_log=[],
        ),
    )
    archived_cv = archive / "submitted_documents" / "cv_submitted.pdf"
    archived_cv.unlink()
    archived_cv.symlink_to(cv_source)

    assert not builder.verify(archive)


def test_archive_creation_rejects_a_symlinked_company_directory(tmp_path: Path) -> None:
    root = tmp_path / "archives"
    company_parent = root / "candidate_alpha" / str(datetime.now(UTC).year)
    company_parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (company_parent / "fictional-company").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="contains a symlink"):
        ApplicationArchiveBuilder(root).create(
            candidate_id="candidate_alpha",
            application_id=UUID("00000000-0000-0000-0000-000000000008"),
            data=ApplicationArchiveData(
                candidate_snapshot={},
                job_snapshot={
                    "company": "Fictional Company",
                    "title": "Engineer",
                    "external_id": "job-8",
                },
                scoring_results={},
                generated_document_references=[],
                answers=[],
                validation_report={"valid": True},
                event_log=[],
                required_document_kinds=(),
            ),
        )
    assert not tuple(outside.iterdir())
