from __future__ import annotations

from app.domain.enums import ReviewDecision
from app.materials.contracts import (
    GenerationRequest,
    GenerationResult,
    MaterialReview,
    ValidationIssue,
)
from app.materials.validation import MaterialValidator


class IndependentMaterialReviewer:
    def __init__(self, validator: MaterialValidator | None = None) -> None:
        self._validator = validator or MaterialValidator()

    def review(self, request: GenerationRequest, result: GenerationResult) -> MaterialReview:
        issues = list(self._validator.validate(result).issues)
        approved = {fact.fact_id: fact.text for fact in request.approved_facts}
        for document in result.documents:
            for claim in document.claims:
                if any(
                    approved.get(evidence_id) == claim.text for evidence_id in claim.evidence_ids
                ):
                    continue
                issues.append(
                    ValidationIssue(
                        code="unsupported_claim",
                        severity="error",
                        message="Claim is not supported by an approved fact with matching text.",
                        document_kind=document.kind,
                    )
                )
        answers_supported = all(
            answer.supported and answer.approved_source_key is not None for answer in result.answers
        )
        if not answers_supported:
            issues.append(
                ValidationIssue(
                    code="unsupported_answer",
                    severity="error",
                    message="At least one answer lacks a unique approved source.",
                )
            )
        documents_supported = not any(
            issue.code in {"unsupported_claim", "wrong_company", "content_hash_mismatch"}
            for issue in issues
        )
        passed = (
            documents_supported
            and answers_supported
            and not any(issue.severity == "error" for issue in issues)
        )
        return MaterialReview(
            decision=ReviewDecision.PASS if passed else ReviewDecision.FAIL,
            semantic_review_passed=passed,
            documents_supported=documents_supported,
            answers_supported=answers_supported,
            issues=tuple(issues),
        )
