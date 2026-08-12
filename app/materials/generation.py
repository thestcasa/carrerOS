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
        agent_version="deterministic-material-generator-v3",
        model_version="deterministic-material-v3",
        prompt_version="candidate-letter-v2",
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
                    f"I am writing to apply for the {request.target.title} role at "
                    f"{request.target.company}. My background combines the practical experience "
                    "and technical work most relevant to the responsibilities of this position."
                ),
                *(f"{claim.text}." for claim in claims),
            ]
            safe_context = (
                (
                    "Across these examples, I have learned to translate open-ended requirements "
                    "into reliable technical work, communicate trade-offs clearly, and improve "
                    "solutions through testing and iteration."
                ),
                (
                    "I am especially motivated by roles where software, data, and machine learning "
                    "come together to solve concrete product or operational problems."
                ),
                (
                    "I value teams that combine strong engineering standards with curiosity, "
                    "ownership, and close collaboration across technical and business functions."
                ),
                (
                    "My approach is practical and evidence-driven: understand the problem, build "
                    "a reproducible solution, validate the result, and make it maintainable for "
                    "the people who use it."
                ),
                (
                    "I would bring a broad early-career foundation, a willingness to learn "
                    "quickly, "
                    "and the discipline to be transparent about assumptions and limitations."
                ),
                (
                    "I am comfortable moving between analysis and implementation, and I enjoy "
                    "turning complex technical details into decisions that a wider team can use."
                ),
                (
                    "I would welcome the opportunity to discuss the role, the team's priorities, "
                    "and how my experience could contribute from the start."
                ),
                (
                    "Thank you for considering my application. I would be glad to provide any "
                    "additional information that would be useful."
                ),
            )
            closing = f"Sincerely,\n{request.candidate_name}"
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
