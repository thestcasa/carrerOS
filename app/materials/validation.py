from __future__ import annotations

import hashlib

from app.materials.contracts import GenerationResult, ValidationIssue, ValidationReport


class MaterialValidator:
    def validate(self, result: GenerationResult) -> ValidationReport:
        issues: list[ValidationIssue] = []
        seen_kinds = set()
        for document in result.documents:
            if document.kind in seen_kinds:
                issues.append(
                    ValidationIssue(
                        code="duplicate_document_kind",
                        severity="error",
                        message=f"More than one {document.kind.value} was generated.",
                        document_kind=document.kind,
                    )
                )
            seen_kinds.add(document.kind)
            if (
                document.company.casefold() != result.target.company.casefold()
                or result.target.company.casefold() not in document.content.casefold()
            ):
                issues.append(
                    ValidationIssue(
                        code="wrong_company",
                        severity="error",
                        message="Document company does not match the job target.",
                        document_kind=document.kind,
                    )
                )
            actual_hash = hashlib.sha256(document.content.encode("utf-8")).hexdigest()
            if actual_hash != document.content_sha256:
                issues.append(
                    ValidationIssue(
                        code="content_hash_mismatch",
                        severity="error",
                        message="Document content does not match its recorded digest.",
                        document_kind=document.kind,
                    )
                )
            word_count = len(document.content.split())
            if document.minimum_words is not None and word_count < document.minimum_words:
                issues.append(
                    ValidationIssue(
                        code="document_below_minimum_words",
                        severity="error",
                        message=(
                            f"Document contains {word_count} words; minimum is "
                            f"{document.minimum_words}."
                        ),
                        document_kind=document.kind,
                    )
                )
            if document.maximum_words is not None and word_count > document.maximum_words:
                issues.append(
                    ValidationIssue(
                        code="document_above_maximum_words",
                        severity="error",
                        message=(
                            f"Document contains {word_count} words; maximum is "
                            f"{document.maximum_words}."
                        ),
                        document_kind=document.kind,
                    )
                )
            if not document.claims:
                issues.append(
                    ValidationIssue(
                        code="document_has_no_claims",
                        severity="error",
                        message="Document contains no approved claims.",
                        document_kind=document.kind,
                    )
                )
            for claim in document.claims:
                if claim.text not in document.content:
                    issues.append(
                        ValidationIssue(
                            code="claim_missing_from_content",
                            severity="error",
                            message="A declared claim is absent from document content.",
                            document_kind=document.kind,
                        )
                    )
        return ValidationReport(
            valid=not any(issue.severity == "error" for issue in issues), issues=tuple(issues)
        )
