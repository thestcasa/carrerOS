from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.applications import (
    ApplicationConflictError,
    ApplicationDetail,
    ApplicationNotFoundError,
    ApplicationService,
    MaterialRevisionRequest,
)
from app.applications.contracts import DocumentView
from app.candidates.service import CandidateService
from app.db import build_session_factory
from app.discovery.verification import StoredFixtureJobSourceVerifier
from app.domain.enums import ApplicationState, DocumentKind
from app.domain.models import AgentReview, ApplicationArtifact, ApplicationDocument, Base
from app.job_service import DiscoveryRequest, JobService


def _services(
    candidates_root: Path, runtime_root: Path
) -> tuple[JobService, ApplicationService, sessionmaker[Session]]:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(candidates_root)
    source_verifier = StoredFixtureJobSourceVerifier()
    return (
        JobService(sessions, candidates, source_verifier),
        ApplicationService(
            sessions,
            candidates,
            runtime_root,
            source_verifier=source_verifier,
        ),
        sessions,
    )


def _lower_fixture_threshold(candidates_root: Path) -> None:
    path = candidates_root / "example_candidate" / "scoring_rules.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["application_threshold"] = 40
    data["human_review_threshold"] = 30
    path.write_text(json.dumps(data), encoding="utf-8")


def _job(job_service: JobService, external_id: int) -> UUID:
    discovered = job_service.discover(
        DiscoveryRequest(
            candidate_id="example_candidate",
            platform="greenhouse",
            company="Fictional Robotics Ltd",
            company_domain="fictional-robotics.invalid",
            payloads=(
                {
                    "id": external_id,
                    "internal_job_id": f"REQ-REVISION-{external_id}",
                    "title": "Machine Learning Engineer",
                    "content": "Build truthful synthetic machine-learning services.",
                    "location": {"name": "Exampleton"},
                    "absolute_url": (f"https://boards.greenhouse.io/fictional/jobs/{external_id}"),
                },
            ),
        ),
        f"discover-revision-{external_id}",
    )
    job_id = discovered.job_ids[0]
    job_service.analyze("example_candidate", job_id, f"analyze-revision-{external_id}")
    return job_id


def _generated_cv(
    candidates_root: Path, runtime_root: Path, external_id: int
) -> tuple[ApplicationService, sessionmaker[Session], ApplicationDetail, DocumentView]:
    _lower_fixture_threshold(candidates_root)
    jobs, applications, sessions = _services(candidates_root, runtime_root)
    generated = applications.generate_materials(
        "example_candidate",
        _job(jobs, external_id),
        f"generate-revision-{external_id}",
    )
    cv = next(
        document
        for document in generated.documents
        if document.kind == "cv" and document.version == 1
    )
    return applications, sessions, generated, cv


def _content_without_last_fact(content: str) -> str:
    paragraphs = content.split("\n\n")
    assert len(paragraphs) >= 3
    assert all(paragraph.startswith("- ") for paragraph in paragraphs[1:])
    return "\n\n".join(paragraphs[:-1])


def test_cv_revision_appends_version_with_provenance_pdf_and_review_references(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    applications, sessions, generated, original_cv = _generated_cv(
        copied_candidates_root, tmp_path / "runtime", 8101
    )
    revised_content = _content_without_last_fact(original_cv.content)
    revision = MaterialRevisionRequest(
        document_id=original_cv.document_id,
        base_version=1,
        content=revised_content,
        reason="Remove the least relevant approved fact.",
    )

    revised = applications.revise_material(
        "example_candidate",
        generated.application_id,
        revision,
        "revise-material-8101",
    )
    replay = applications.revise_material(
        "example_candidate",
        generated.application_id,
        revision,
        "revise-material-8101",
    )

    assert replay == revised
    assert revised.state is ApplicationState.REVIEW_PENDING
    versioned_cv = sorted(
        (document for document in revised.documents if document.kind == "cv"),
        key=lambda document: document.version,
    )
    assert [document.version for document in versioned_cv] == [1, 2]
    assert versioned_cv[0].content == original_cv.content
    assert versioned_cv[0].sha256 == original_cv.sha256
    assert versioned_cv[0].immutable
    assert versioned_cv[1].content == revised_content
    assert versioned_cv[1].base_document_id == original_cv.document_id
    assert versioned_cv[1].revision_actor == "local-user"
    assert versioned_cv[1].provenance
    assert {
        str(evidence_id)
        for entry in versioned_cv[1].provenance
        for evidence_id in cast(list[str], entry["evidence_ids"])
    } == set(versioned_cv[1].evidence_ids)
    assert all(cast(list[str], entry["source_paths"]) for entry in versioned_cv[1].provenance)

    artifacts = applications.list_artifacts("example_candidate", generated.application_id)
    report = next(
        artifact
        for artifact in artifacts
        if artifact.kind == "render_report_cv" and artifact.version == 2
    )
    rendered_pdf = next(
        artifact
        for artifact in artifacts
        if artifact.kind == "rendered_cv" and artifact.version == 2
    )
    latex_source = next(
        artifact
        for artifact in artifacts
        if artifact.kind == "latex_source_cv" and artifact.version == 2
    )
    assert report.metadata["source_sha256"] == versioned_cv[1].sha256
    assert report.metadata["document_version"] == 2
    assert report.metadata["base_document_id"] == str(original_cv.document_id)
    assert report.metadata["manual_revision"] is True
    assert rendered_pdf.metadata == report.metadata
    assert latex_source.metadata["semantic_source_sha256"] == versioned_cv[1].sha256
    assert latex_source.sha256 == report.metadata["latex_sha256"]
    latex_bytes = applications.artifact_path(
        "example_candidate", generated.application_id, latex_source.artifact_id
    ).read_bytes()
    assert latex_bytes.startswith(b"\\documentclass")
    assert latex_bytes.rstrip().endswith(b"\\end{document}")
    assert (
        applications.artifact_path(
            "example_candidate", generated.application_id, rendered_pdf.artifact_id
        )
        .read_bytes()
        .startswith(b"%PDF-")
    )

    assert revised.review is not None and revised.review.semantic_passed
    render_reports = cast(list[dict[str, object]], revised.review.report["render_reports"])
    reviewed_cv = next(item for item in render_reports if item["document_kind"] == "cv")
    assert reviewed_cv["document_version"] == 2
    assert reviewed_cv["source_sha256"] == versioned_cv[1].sha256
    assert reviewed_cv["pdf_sha256"] == rendered_pdf.sha256

    with sessions() as session:
        assert (
            session.scalar(
                select(func.count(ApplicationDocument.id)).where(
                    ApplicationDocument.application_id == generated.application_id,
                    ApplicationDocument.kind == DocumentKind.CV,
                )
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count(AgentReview.id)).where(
                    AgentReview.application_id == generated.application_id
                )
            )
            == 2
        )

    changed_request = revision.model_copy(update={"reason": "A different reason."})
    with pytest.raises(ApplicationConflictError, match="reused with another request"):
        applications.revise_material(
            "example_candidate",
            generated.application_id,
            changed_request,
            "revise-material-8101",
        )


def test_material_revision_denies_stale_unsupported_noop_cross_candidate_and_approved_state(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    candidate_beta = copied_candidates_root / "candidate_beta"
    shutil.copytree(copied_candidates_root / "example_candidate", candidate_beta)
    profile_path = candidate_beta / "profile.yaml"
    profile_path.write_text(
        profile_path.read_text(encoding="utf-8").replace(
            "candidate_id: example_candidate", "candidate_id: candidate_beta"
        ),
        encoding="utf-8",
    )
    identity_path = candidate_beta / "identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity["candidate_id"] = "candidate_beta"
    identity_path.write_text(json.dumps(identity), encoding="utf-8")

    applications, _sessions, generated, original_cv = _generated_cv(
        copied_candidates_root, tmp_path / "runtime", 8102
    )
    changed_content = _content_without_last_fact(original_cv.content)
    base_request = MaterialRevisionRequest(
        document_id=original_cv.document_id,
        base_version=1,
        content=changed_content,
    )

    with pytest.raises(ApplicationConflictError, match="must change"):
        applications.revise_material(
            "example_candidate",
            generated.application_id,
            base_request.model_copy(update={"content": original_cv.content}),
            "revision-noop-8102",
        )

    with pytest.raises(ApplicationConflictError, match="not present in the approved snapshot"):
        applications.revise_material(
            "example_candidate",
            generated.application_id,
            base_request.model_copy(
                update={"content": f"{changed_content}\n\n- Invented a fictional credential."}
            ),
            "revision-unsupported-8102",
        )

    with pytest.raises(ApplicationNotFoundError):
        applications.revise_material(
            "candidate_beta",
            generated.application_id,
            base_request,
            "revision-cross-candidate-8102",
        )

    applications.revise_material(
        "example_candidate",
        generated.application_id,
        base_request,
        "revision-success-8102",
    )
    with pytest.raises(ApplicationConflictError, match="base version is stale"):
        applications.revise_material(
            "example_candidate",
            generated.application_id,
            base_request,
            "revision-stale-8102",
        )

    applications.approve_materials(
        "example_candidate", generated.application_id, "approve-revision-8102"
    )
    with pytest.raises(ApplicationConflictError, match="review is pending or failed"):
        applications.revise_material(
            "example_candidate",
            generated.application_id,
            base_request.model_copy(update={"document_id": original_cv.document_id}),
            "revision-after-approval-8102",
        )


def test_material_revision_denies_tampered_base_render_report(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    applications, _sessions, generated, original_cv = _generated_cv(
        copied_candidates_root, tmp_path / "runtime", 8103
    )
    report = next(
        artifact
        for artifact in applications.list_artifacts("example_candidate", generated.application_id)
        if artifact.kind == "render_report_cv" and artifact.version == 1
    )
    report_path = applications.artifact_path(
        "example_candidate", generated.application_id, report.artifact_id
    )
    report_path.write_bytes(report_path.read_bytes() + b"tampered")

    with pytest.raises(ApplicationConflictError, match="render report is missing or corrupted"):
        applications.revise_material(
            "example_candidate",
            generated.application_id,
            MaterialRevisionRequest(
                document_id=original_cv.document_id,
                base_version=1,
                content=_content_without_last_fact(original_cv.content),
            ),
            "revision-tampered-report-8103",
        )

    with _sessions() as session:
        assert (
            session.scalar(
                select(func.count(ApplicationArtifact.id)).where(
                    ApplicationArtifact.application_id == generated.application_id,
                    ApplicationArtifact.version == 2,
                )
            )
            == 0
        )
