from __future__ import annotations

import hashlib

from app.domain.enums import DocumentKind
from app.materials.contracts import (
    ApprovedAnswerFact,
    ApprovedFact,
    Claim,
    GeneratedAnswer,
    GeneratedDocument,
    GenerationRequest,
    GenerationResult,
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class DeterministicMaterialGenerator:
    """Renders only supplied approved facts; it never invents or expands claims."""

    def generate(self, request: GenerationRequest) -> GenerationResult:
        facts = tuple(sorted(request.approved_facts, key=lambda fact: fact.fact_id))
        documents = tuple(
            self._document(kind, request, facts) for kind in request.requested_documents
        )
        answers = tuple(
            self._answer(prompt.question_key, prompt.question, request.approved_answers)
            for prompt in request.answer_prompts
        )
        return GenerationResult(
            candidate_id=request.candidate_id,
            application_id=request.application_id,
            target=request.target,
            documents=documents,
            answers=answers,
        )

    @staticmethod
    def _document(
        kind: DocumentKind,
        request: GenerationRequest,
        facts: tuple[ApprovedFact, ...],
    ) -> GeneratedDocument:
        heading = (
            f"CV — {request.target.title} at {request.target.company}"
            if kind == DocumentKind.CV
            else f"Application for {request.target.title} at {request.target.company}"
        )
        claims = tuple(Claim(text=fact.text, evidence_ids=(fact.fact_id,)) for fact in facts)
        content = "\n\n".join((heading, *(f"- {claim.text}" for claim in claims)))
        return GeneratedDocument(
            kind=kind,
            company=request.target.company,
            content=content,
            claims=claims,
            content_sha256=_sha256(content),
        )

    @staticmethod
    def _answer(
        question_key: str,
        question: str,
        approved_answers: tuple[ApprovedAnswerFact, ...],
    ) -> GeneratedAnswer:
        matches = [answer for answer in approved_answers if answer.key == question_key]
        if len(matches) != 1:
            return GeneratedAnswer(
                question_key=question_key,
                question=question,
                answer="Human review required",
                approved_source_key=None,
                evidence_ids=(),
                supported=False,
            )
        match = matches[0]
        return GeneratedAnswer(
            question_key=question_key,
            question=question,
            answer=match.answer,
            approved_source_key=match.key,
            evidence_ids=match.evidence_ids,
            supported=True,
        )
