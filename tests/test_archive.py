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
    assert set(manifest["files"]) == {
        "candidate_snapshot.json",
        "job_snapshot.json",
        "scoring_results.json",
        "generated_document_references.json",
        "answers.json",
        "validation_report.json",
        "event_log.json",
    }
    with pytest.raises(ArchiveExistsError):
        builder.create(candidate_id="candidate_alpha", application_id=application_id, data=data)

    (archive_path / "answers.json").write_text("[]\n", encoding="utf-8")
    assert builder.verify(archive_path) is False
