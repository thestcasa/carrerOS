from __future__ import annotations

from typing import TypedDict

from app.agents.fakes import (
    FakeDocumentGenerationAgent,
    FakeIndependentReviewAgent,
    FakeJobAnalysisAgent,
)
from app.domain.enums import DocumentKind, ReviewDecision
from app.orchestrator import ApplicationOrchestrator


class _PreparationArguments(TypedDict):
    candidate_id: str
    candidate_snapshot_json: str
    job_snapshot_json: str
    approved_answers_json: str
    document_rules_json: str
    policy_snapshot_json: str
    scoring_version: int
    application_threshold: int
    scoring_weights: tuple[tuple[str, float], ...]
    requested_documents: tuple[DocumentKind, ...]


def test_fake_agents_are_deterministic_and_independent() -> None:
    orchestrator = ApplicationOrchestrator(
        FakeJobAnalysisAgent(score=88),
        FakeDocumentGenerationAgent(),
        FakeIndependentReviewAgent(),
    )
    arguments: _PreparationArguments = {
        "candidate_id": "candidate_alpha",
        "candidate_snapshot_json": '{"candidate_id":"candidate_alpha"}',
        "job_snapshot_json": '{"job_id":"fictional-job-1"}',
        "approved_answers_json": "{}",
        "document_rules_json": "{}",
        "policy_snapshot_json": "{}",
        "scoring_version": 1,
        "application_threshold": 80,
        "scoring_weights": (("skills", 1.0),),
        "requested_documents": (DocumentKind.CV,),
    }

    first = orchestrator.prepare(**arguments)
    second = orchestrator.prepare(**arguments)

    assert first.analysis.total_score == second.analysis.total_score == 88
    assert first.analysis.request_id != second.analysis.request_id
    assert first.generation.request_id != first.analysis.request_id
    assert first.review.request_id != first.generation.request_id
    assert first.review.decision is ReviewDecision.PASS


def test_independent_review_failure_is_explicit() -> None:
    result = ApplicationOrchestrator(
        FakeJobAnalysisAgent(),
        FakeDocumentGenerationAgent(),
        FakeIndependentReviewAgent(passes=False),
    ).prepare(
        candidate_id="candidate_alpha",
        candidate_snapshot_json="{}",
        job_snapshot_json="{}",
        approved_answers_json="{}",
        document_rules_json="{}",
        policy_snapshot_json="{}",
        scoring_version=1,
        application_threshold=80,
        scoring_weights=(("skills", 1.0),),
        requested_documents=(DocumentKind.CV,),
    )

    assert result.review.semantic_review_passed is False
    assert result.review.decision is ReviewDecision.FAIL
