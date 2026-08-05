from __future__ import annotations

from app.domain.enums import ReviewDecision
from app.materials.contracts import (
    GenerationRequest,
    GenerationResult,
    MaterialReview,
    RenderValidationReport,
    ValidationIssue,
)
from app.materials.validation import MaterialValidator


class IndependentMaterialReviewer:
    def __init__(self, validator: MaterialValidator | None = None) -> None:
        self._validator = validator or MaterialValidator()

    def review(
        self,
        request: GenerationRequest,
        result: GenerationResult,
        render_reports: tuple[RenderValidationReport, ...] = (),
    ) -> MaterialReview:
        issues = list(self._validator.validate(result).issues)
        issues.extend(issue for report in render_reports for issue in report.issues)
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
        renders_valid = len(render_reports) == len(result.documents) and all(
            report.valid for report in render_reports
        )
        documents_supported = renders_valid and not any(
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
            render_reports=render_reports,
        )
