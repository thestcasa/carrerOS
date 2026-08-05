from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.archive import ApplicationArchiveBuilder, ApplicationArchiveData, ArchiveExistsError


def test_archive_hashes_detect_mutation_and_archive_cannot_be_overwritten(tmp_path: Path) -> None:
    builder = ApplicationArchiveBuilder(tmp_path / "archives")
    application_id = uuid4()
    cv_source = tmp_path / "fictional-cv.txt"
    cv_source.write_text("Fictional candidate CV", encoding="utf-8")
    data = ApplicationArchiveData(
        candidate_snapshot={"candidate_id": "candidate_alpha", "version": 1},
        job_snapshot={"job_id": "fictional-job-1"},
        scoring_results={"score": 90},
        generated_document_references=[
            {"kind": "cv", "sha256": "0" * 64, "storage_uri": str(cv_source)}
        ],
        answers=[{"key": "authorization", "answer": "Yes", "supported": True}],
        validation_report={"passed": True},
        event_log=[{"event": "review_passed"}],
    )

    archive_path = builder.create(
        candidate_id="candidate_alpha", application_id=application_id, data=data
    )

    assert builder.verify(archive_path) is True
    manifest = json.loads((archive_path / "manifest.json").read_text(encoding="utf-8"))
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
