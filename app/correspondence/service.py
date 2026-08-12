from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable

from app.correspondence.models import (
    ApplicationReference,
    ArchivedApplicationArtifacts,
    CorrespondenceKind,
    CorrespondenceRecord,
    InterviewPreparationPackage,
    MessageFixture,
)

_CLASSIFICATION_RULES: tuple[tuple[CorrespondenceKind, tuple[str, ...]], ...] = (
    (
        CorrespondenceKind.OFFER,
        ("offer of employment", "job offer", "offer letter", "pleased to offer"),
    ),
    (
        CorrespondenceKind.INTERVIEW,
        ("interview invitation", "schedule an interview", "interview availability", "next round"),
    ),
    (
        CorrespondenceKind.REJECTION,
        ("not moving forward", "will not be progressing", "other candidates", "unsuccessful"),
    ),
    (
        CorrespondenceKind.CONFIRMATION,
        ("application received", "received your application", "thank you for applying"),
    ),
    (
        CorrespondenceKind.RECRUITER,
        ("recruiter", "talent acquisition", "your background", "career opportunity"),
    ),
)


def _normalized_text(*parts: str) -> str:
    return " ".join(" ".join(parts).casefold().split())


def _tokens(value: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", value.casefold()))


def _message_hash(message: MessageFixture) -> str:
    canonical = json.dumps(
        message.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _artifact_hash(artifacts: ArchivedApplicationArtifacts) -> str:
    canonical = json.dumps(
        artifacts.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


class CorrespondenceService:
    """Classifies supplied messages; intentionally has no send or reply capability."""

    def ingest(
        self,
        *,
        candidate_id: str,
        message: MessageFixture,
        applications: Iterable[ApplicationReference],
    ) -> CorrespondenceRecord:
        candidates = tuple(
            application for application in applications if application.candidate_id == candidate_id
        )
        kind = self._classify(message)
        application, reason = self._associate(message, candidates)
        return CorrespondenceRecord(
            provider_message_id=message.provider_message_id,
            message_sha256=_message_hash(message),
            kind=kind,
            candidate_id=candidate_id,
            application_id=application.application_id if application is not None else None,
            association_reason=reason,
            received_at=message.received_at,
            subject=message.subject,
        )

    def prepare_interview(
        self, artifacts: ArchivedApplicationArtifacts
    ) -> InterviewPreparationPackage:
        technical = tuple(
            f"How have you applied {skill} in a production or project setting?"
            for skill in artifacts.required_skills
        )
        behavioral = (
            f"Why are you interested in {artifacts.company} and this {artifacts.job_title} role?",
            "Describe a difficult project decision and the evidence you used to make it.",
            "Describe a time you received critical feedback and how you responded.",
        )
        return InterviewPreparationPackage(
            candidate_id=artifacts.candidate_id,
            application_id=artifacts.application_id,
            company=artifacts.company,
            job_title=artifacts.job_title,
            exact_cv=artifacts.exact_cv,
            exact_cover_letter=artifacts.exact_cover_letter,
            submitted_answers=artifacts.submitted_answers,
            original_job_description=artifacts.original_job_description,
            job_score=artifacts.job_score,
            score_rationale=artifacts.score_rationale,
            candidate_job_match_summary=artifacts.candidate_job_match_summary,
            company_notes=artifacts.company_notes,
            likely_technical_questions=technical,
            likely_behavioral_questions=behavioral,
            relevant_projects=artifacts.relevant_projects,
            unsupported_areas=artifacts.unsupported_areas,
            salary_answer_submitted=artifacts.salary_answer_submitted,
            recruiter_correspondence=artifacts.recruiter_correspondence,
            source_artifacts_sha256=_artifact_hash(artifacts),
        )

    @staticmethod
    def _classify(message: MessageFixture) -> CorrespondenceKind:
        content = _normalized_text(message.subject, message.body_text)
        for kind, phrases in _CLASSIFICATION_RULES:
            if any(phrase in content for phrase in phrases):
                return kind
        return CorrespondenceKind.UNKNOWN

    @staticmethod
    def _associate(
        message: MessageFixture,
        applications: tuple[ApplicationReference, ...],
    ) -> tuple[ApplicationReference | None, str]:
        content = _normalized_text(message.subject, message.body_text, message.sender)
        exact = tuple(
            application
            for application in applications
            if any(reference.casefold() in content for reference in application.external_references)
        )
        if len(exact) == 1:
            return exact[0], "unique_external_reference"
        if len(exact) > 1:
            return None, "ambiguous_external_reference"

        scored: list[tuple[int, ApplicationReference]] = []
        content_tokens = _tokens(content)
        for application in applications:
            company_tokens = _tokens(application.company)
            title_tokens = _tokens(application.job_title)
            domain_match = application.company_domain.casefold() in content
            company_match = bool(company_tokens) and company_tokens <= content_tokens
            title_overlap = len(title_tokens & content_tokens)
            score = int(domain_match) * 4 + int(company_match) * 3 + title_overlap
            if score >= 4:
                scored.append((score, application))
        if not scored:
            return None, "no_deterministic_match"
        best_score = max(score for score, _application in scored)
        best = tuple(application for score, application in scored if score == best_score)
        if len(best) != 1:
            return None, "ambiguous_application_match"
        return best[0], "unique_company_and_role_match"
