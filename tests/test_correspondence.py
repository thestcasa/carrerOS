from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.correspondence import (
    ApplicationReference,
    ArchivedApplicationArtifacts,
    CorrespondenceKind,
    CorrespondenceService,
    MessageFixture,
    SubmittedAnswer,
)

APPLICATION_ID = UUID("00000000-0000-0000-0000-000000000101")


def _message(subject: str, body: str) -> MessageFixture:
    return MessageFixture(
        provider_message_id=f"fixture-{subject}",
        sender="recruiting@fictional-robotics.invalid",
        recipients=("morgan@example.invalid",),
        subject=subject,
        body_text=body,
        received_at=datetime(2027, 3, 1, 10, tzinfo=UTC),
    )


def _application(application_id: UUID = APPLICATION_ID) -> ApplicationReference:
    return ApplicationReference(
        candidate_id="candidate_alpha",
        application_id=application_id,
        company="Fictional Robotics",
        company_domain="fictional-robotics.invalid",
        job_title="Machine Learning Engineer",
        external_references=("FR-ML-42",),
    )


@pytest.mark.parametrize(
    ("subject", "body", "expected"),
    [
        ("Application received", "Thank you for applying.", CorrespondenceKind.CONFIRMATION),
        ("Application update", "We are not moving forward.", CorrespondenceKind.REJECTION),
        (
            "A career opportunity",
            "A recruiter liked your background.",
            CorrespondenceKind.RECRUITER,
        ),
        ("Interview invitation", "Please share your availability.", CorrespondenceKind.INTERVIEW),
        ("Job offer", "We are pleased to offer employment.", CorrespondenceKind.OFFER),
    ],
)
def test_fixture_messages_are_classified_deterministically(
    subject: str, body: str, expected: CorrespondenceKind
) -> None:
    service = CorrespondenceService()
    first = service.ingest(
        candidate_id="candidate_alpha",
        message=_message(subject, body),
        applications=(_application(),),
    )
    second = service.ingest(
        candidate_id="candidate_alpha",
        message=_message(subject, body),
        applications=(_application(),),
    )

    assert first.kind is expected
    assert first.message_sha256 == second.message_sha256


def test_association_prefers_unique_external_reference_and_is_candidate_isolated() -> None:
    other_candidate = _application(UUID("00000000-0000-0000-0000-000000000202")).model_copy(
        update={"candidate_id": "candidate_beta"}
    )
    record = CorrespondenceService().ingest(
        candidate_id="candidate_alpha",
        message=_message("Interview invitation FR-ML-42", "Please choose a time."),
        applications=(other_candidate, _application()),
    )

    assert record.application_id == APPLICATION_ID
    assert record.association_reason == "unique_external_reference"


def test_ambiguous_association_fails_closed() -> None:
    second = _application(UUID("00000000-0000-0000-0000-000000000303")).model_copy(
        update={"external_references": ("FR-ML-42",)}
    )
    record = CorrespondenceService().ingest(
        candidate_id="candidate_alpha",
        message=_message("Update FR-ML-42", "We have news."),
        applications=(_application(), second),
    )

    assert record.application_id is None
    assert record.association_reason == "ambiguous_external_reference"


def test_interview_package_preserves_supplied_archive_and_is_immutable() -> None:
    artifacts = ArchivedApplicationArtifacts(
        candidate_id="candidate_alpha",
        application_id=APPLICATION_ID,
        company="Fictional Robotics",
        job_title="Machine Learning Engineer",
        exact_cv="Exact archived CV bytes represented as text.",
        exact_cover_letter="Exact fictional cover letter.",
        submitted_answers=(SubmittedAnswer(question="Salary?", answer="EUR 50,000"),),
        original_job_description="Build deterministic fictional ML systems.",
        job_score=88,
        score_rationale="Strong evidence-backed Python and ML match.",
        candidate_job_match_summary="Approved project evidence matches the core role.",
        company_notes=("Fictional local pilot company.",),
        required_skills=("Python", "model monitoring"),
        relevant_projects=("project_fictional_monitoring",),
        unsupported_areas=("Do not claim Kubernetes production ownership.",),
        salary_answer_submitted="EUR 50,000",
        recruiter_correspondence=("Interview invitation received.",),
    )
    package = CorrespondenceService().prepare_interview(artifacts)

    assert package.exact_cv == artifacts.exact_cv
    assert package.submitted_answers == artifacts.submitted_answers
    assert package.unsupported_areas == artifacts.unsupported_areas
    assert package.likely_technical_questions == (
        "How have you applied Python in a production or project setting?",
        "How have you applied model monitoring in a production or project setting?",
    )
    with pytest.raises(ValidationError):
        package.__setattr__("job_score", 99)


def test_service_exposes_no_auto_reply_or_send_capability() -> None:
    public_methods = {name for name in dir(CorrespondenceService) if not name.startswith("_")}

    assert public_methods == {"ingest", "prepare_interview"}
