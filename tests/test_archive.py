from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.archive import ApplicationArchiveBuilder, ApplicationArchiveData, ArchiveExistsError


def test_archive_hashes_detect_mutation_and_archive_cannot_be_overwritten(tmp_path: Path) -> None:
    builder = ApplicationArchiveBuilder(tmp_path / "archives")
    application_id = uuid4()
    data = ApplicationArchiveData(
        candidate_snapshot={"candidate_id": "candidate_alpha", "version": 1},
        job_snapshot={"job_id": "fictional-job-1"},
        scoring_results={"score": 90},
        generated_document_references=[{"kind": "cv", "sha256": "0" * 64}],
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

    (archive_path / "answers" / "final_answers.json").write_text("[]\n", encoding="utf-8")
    assert builder.verify(archive_path) is False
