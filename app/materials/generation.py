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
    MaterialAgentProvenance,
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class DeterministicMaterialGenerator:
    """Renders only supplied approved facts; it never invents or expands claims."""

    provenance = MaterialAgentProvenance(
        agent_version="deterministic-material-generator-v2",
        model_version="deterministic-material-v2",
        prompt_version="material-policy-v1",
    )

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
        claims = tuple(
            Claim(text=fact.text, evidence_ids=(fact.fact_id,))
            for fact in facts
            if kind in fact.document_kinds
        )
        if kind == DocumentKind.CV:
            heading = f"CV — {request.target.title} at {request.target.company}"
            content = "\n\n".join((heading, *(f"- {claim.text}" for claim in claims)))
            minimum_words = None
            maximum_words = None
        else:
            heading = f"Application for {request.target.title} at {request.target.company}"
            paragraphs = [
                heading,
                "Dear Hiring Team,",
                (
                    f"I am applying for the {request.target.title} role at "
                    f"{request.target.company}. This letter uses only approved candidate evidence "
                    "and the role identity recorded in the source posting."
                ),
                *(f"{claim.text}." for claim in claims),
            ]
            safe_context = (
                (
                    "The selected examples were chosen for their direct overlap with the recorded "
                    "role requirements; no assumptions about the company have been added."
                ),
                (
                    "I would welcome the opportunity to discuss how this documented experience "
                    "relates to the responsibilities of the position."
                ),
                (
                    "The accompanying CV provides the underlying chronology, while this letter "
                    "highlights only the most relevant approved evidence."
                ),
                (
                    "I have kept the application specific to this role and have not relied on "
                    "unsupported achievements, metrics, or company claims."
                ),
                (
                    "Thank you for considering this evidence-based application. I would be glad "
                    "to answer further questions in a structured interview."
                ),
                (
                    "Where the posting leaves a detail unspecified, I have left it unspecified "
                    "rather than introduce a generic or unverified company statement."
                ),
                (
                    "Each factual statement about my background can be traced to the approved "
                    "candidate record supplied with this application."
                ),
                (
                    "Rather than repeat the full CV, I have limited this letter to one or two "
                    "experience and project groups selected for relevance."
                ),
                (
                    "The application materials preserve the original dates, terminology, and "
                    "evidence so that the fit can be assessed without exaggeration."
                ),
                (
                    "I am interested in a conversation grounded in the responsibilities stated "
                    "for this position and the documented work summarized here."
                ),
                (
                    "This scope keeps the letter concise, role-specific, and suitable for direct "
                    "comparison with the attached evidence."
                ),
            )
            closing = "Sincerely,\nCandidate"
            for paragraph in safe_context:
                prospective = "\n\n".join((*paragraphs, paragraph, closing))
                if len(prospective.split()) > request.cover_letter_max_words:
                    continue
                paragraphs.append(paragraph)
                if len(prospective.split()) >= request.cover_letter_min_words:
                    break
            paragraphs.append(closing)
            content = "\n\n".join(paragraphs)
            minimum_words = request.cover_letter_min_words
            maximum_words = request.cover_letter_max_words
        return GeneratedDocument(
            kind=kind,
            company=request.target.company,
            content=content,
            claims=claims,
            content_sha256=_sha256(content),
            minimum_words=minimum_words,
            maximum_words=maximum_words,
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
