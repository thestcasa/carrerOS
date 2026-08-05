from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from app.domain.enums import DocumentKind, ReviewDecision
from app.materials.contracts import (
    AnswerPrompt,
    ApprovedAnswerFact,
    ApprovedFact,
    Claim,
    GeneratedDocument,
    GenerationRequest,
    GenerationResult,
    JobTarget,
)
from app.materials.generation import DeterministicMaterialGenerator
from app.materials.review import IndependentMaterialReviewer
from app.materials.storage import DraftArtifactStore, DraftVersionExistsError
from app.materials.validation import MaterialValidator


def _request() -> GenerationRequest:
    return GenerationRequest(
        candidate_id="example_candidate",
        application_id=uuid4(),
        target=JobTarget(company="Fictional Robotics Ltd", title="ML Engineer"),
        requested_documents=(DocumentKind.CV, DocumentKind.COVER_LETTER),
        approved_facts=(
            ApprovedFact(
                fact_id="experience_example_1",
                text="Introduced typed API contracts and automated tests.",
                source_path="experience.items[0].achievements[1]",
            ),
        ),
        approved_answers=(
            ApprovedAnswerFact(
                key="work_authorization",
                question_pattern="Are you authorized to work?",
                answer="Yes",
            ),
        ),
        answer_prompts=(
            AnswerPrompt(
                question_key="work_authorization",
                question="Are you authorized to work?",
            ),
        ),
    )


def test_generation_is_deterministic_and_every_claim_has_provenance() -> None:
    request = _request()
    generator = DeterministicMaterialGenerator()

    first = generator.generate(request)
    second = generator.generate(request)

    assert first == second
    assert all(
        claim.evidence_ids == ("experience_example_1",)
        for document in first.documents
        for claim in document.claims
    )
    assert first.answers[0].supported
    assert first.answers[0].approved_source_key == "work_authorization"
    review = IndependentMaterialReviewer().review(request, first)
    assert review.decision == ReviewDecision.PASS


def test_unknown_answer_fails_closed_for_human_review() -> None:
    request = _request().model_copy(
        update={
            "answer_prompts": (
                AnswerPrompt(question_key="salary", question="What salary do you expect?"),
            )
        }
    )

    result = DeterministicMaterialGenerator().generate(request)
    review = IndependentMaterialReviewer().review(request, result)

    assert result.answers[0].answer == "Human review required"
    assert not result.answers[0].supported
    assert review.decision == ReviewDecision.FAIL
    assert {issue.code for issue in review.issues} == {"unsupported_answer"}


def test_validation_and_review_block_wrong_company_and_unsupported_claims() -> None:
    request = _request()
    generated = DeterministicMaterialGenerator().generate(request)
    original = generated.documents[0]
    bad_content = "CV — ML Engineer at Wrong Company\n\n- Won an imaginary industry award."
    bad_document = GeneratedDocument(
        kind=original.kind,
        company="Wrong Company",
        content=bad_content,
        claims=(Claim(text="Won an imaginary industry award.", evidence_ids=("missing_fact",)),),
        content_sha256=hashlib.sha256(bad_content.encode()).hexdigest(),
    )
    tampered = GenerationResult(
        candidate_id=generated.candidate_id,
        application_id=generated.application_id,
        target=generated.target,
        documents=(bad_document,),
        answers=generated.answers,
    )

    validation = MaterialValidator().validate(tampered)
    review = IndependentMaterialReviewer().review(request, tampered)

    assert not validation.valid
    assert "wrong_company" in {issue.code for issue in validation.issues}
    assert review.decision == ReviewDecision.FAIL
    assert {"wrong_company", "unsupported_claim"} <= {issue.code for issue in review.issues}


def test_draft_storage_is_versioned_immutable_and_hash_verified(tmp_path: Path) -> None:
    request = _request()
    document = DeterministicMaterialGenerator().generate(request).documents[0]
    store = DraftArtifactStore(tmp_path)

    first = store.save(
        candidate_id=request.candidate_id,
        application_id=request.application_id,
        version=1,
        document=document,
    )
    second = store.save(
        candidate_id=request.candidate_id,
        application_id=request.application_id,
        version=2,
        document=document,
    )

    assert first != second
    assert store.verify(first)
    with pytest.raises(DraftVersionExistsError):
        store.save(
            candidate_id=request.candidate_id,
            application_id=request.application_id,
            version=1,
            document=document,
        )
    first.write_text(first.read_text().replace("typed API", "fabricated API"))
    assert not store.verify(first)


def test_draft_store_rejects_unsafe_candidate_scope(tmp_path: Path) -> None:
    request = _request()
    document = DeterministicMaterialGenerator().generate(request).documents[0]
    with pytest.raises(ValueError, match="candidate_id"):
        DraftArtifactStore(tmp_path).save(
            candidate_id="../escape",
            application_id=request.application_id,
            version=1,
            document=document,
        )
