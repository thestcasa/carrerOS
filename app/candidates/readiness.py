from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.candidates.models import CandidateConfig, ClaimFact


class ReadinessStatus(StrEnum):
    READY = "READY"
    READY_WITH_WARNINGS = "READY_WITH_WARNINGS"
    BLOCKED = "BLOCKED"
    NOT_CONFIGURED = "NOT_CONFIGURED"


class ReadinessIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    domain: str
    field_path: str
    severity: Literal["warning", "blocking"] = "blocking"


class DomainReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: str
    label: str
    status: ReadinessStatus
    field_path: str
    issues: tuple[ReadinessIssue, ...] = ()


class CapabilityReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability: str
    label: str
    status: ReadinessStatus
    blockers: tuple[str, ...] = ()


class ReadinessReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    status: Literal["ready", "not_ready"]
    issues: tuple[ReadinessIssue, ...]
    domains: tuple[DomainReadiness, ...]
    capabilities: tuple[CapabilityReadiness, ...]


def _issue(code: str, message: str, domain: str, field_path: str) -> ReadinessIssue:
    return ReadinessIssue(code=code, message=message, domain=domain, field_path=field_path)


def _domain(
    domain: str,
    label: str,
    field_path: str,
    configured: bool,
    issues: list[ReadinessIssue],
) -> DomainReadiness:
    own_issues = tuple(issue for issue in issues if issue.domain == domain)
    if not configured:
        status = ReadinessStatus.NOT_CONFIGURED
    elif any(issue.severity == "blocking" for issue in own_issues):
        status = ReadinessStatus.BLOCKED
    elif own_issues:
        status = ReadinessStatus.READY_WITH_WARNINGS
    else:
        status = ReadinessStatus.READY
    return DomainReadiness(
        domain=domain,
        label=label,
        status=status,
        field_path=field_path,
        issues=own_issues,
    )


def _capability(
    capability: str,
    label: str,
    required_domains: tuple[str, ...],
    domains: tuple[DomainReadiness, ...],
    control_blocker: str | None = None,
) -> CapabilityReadiness:
    statuses = {domain.domain: domain.status for domain in domains}
    blockers = [
        domain
        for domain in required_domains
        if statuses[domain] in {ReadinessStatus.BLOCKED, ReadinessStatus.NOT_CONFIGURED}
    ]
    if control_blocker is not None:
        blockers.append(control_blocker)
    return CapabilityReadiness(
        capability=capability,
        label=label,
        status=ReadinessStatus.BLOCKED if blockers else ReadinessStatus.READY,
        blockers=tuple(blockers),
    )


def assess_readiness(config: CandidateConfig) -> ReadinessReport:
    issues: list[ReadinessIssue] = []
    approved_evidence = (
        any(item.approved and not item.archived for item in config.education.items)
        or any(item.approved and not item.archived for item in config.experience.items)
        or any(item.approved and not item.archived for item in config.projects.items)
    )
    approved_languages = any(item.approved and not item.archived for item in config.languages.items)
    checks = (
        (
            config.manifest.active,
            "candidate_inactive",
            "Candidate profile must be active.",
            "profile",
            "manifest.active",
        ),
        (
            config.manifest.validation.profile_approved,
            "profile_not_approved",
            "Candidate profile requires explicit approval.",
            "profile",
            "manifest.validation.profile_approved",
        ),
        (
            config.identity.approved,
            "identity_not_approved",
            "Identity requires explicit candidate approval.",
            "identity",
            "identity.approved",
        ),
        (
            bool(config.biography.summary),
            "missing_biography",
            "Biography summary is required.",
            "biography",
            "biography.summary",
        ),
        (
            config.biography.approved,
            "biography_not_approved",
            "Biography requires explicit candidate approval.",
            "biography",
            "biography.approved",
        ),
        (
            approved_evidence,
            "missing_approved_evidence",
            "At least one approved education, experience, or project is required.",
            "evidence",
            "experience.items",
        ),
        (
            bool(config.skills.categories),
            "missing_skills",
            "At least one skill category is required.",
            "skills",
            "skills.categories",
        ),
        (
            config.skills.approved,
            "skills_not_approved",
            "Skills require explicit candidate approval.",
            "skills",
            "skills.approved",
        ),
        (
            approved_languages,
            "missing_approved_languages",
            "At least one approved language is required.",
            "languages",
            "languages.items",
        ),
        (
            bool(config.career_strategy.target_roles),
            "missing_target_roles",
            "Career strategy needs a target role.",
            "strategy",
            "career_strategy.target_roles",
        ),
        (
            config.career_strategy.approved,
            "career_strategy_not_approved",
            "Career strategy requires explicit candidate approval.",
            "strategy",
            "career_strategy.approved",
        ),
        (
            bool(config.roles.target),
            "missing_role_rules",
            "Role rules need a target role.",
            "strategy",
            "roles.target",
        ),
        (
            config.scoring_rules.approved,
            "scoring_rules_not_approved",
            "Scoring rules require explicit candidate approval.",
            "strategy",
            "scoring_rules.approved",
        ),
        (
            config.preferences.approved,
            "preferences_not_approved",
            "Location, compensation, and availability preferences require approval.",
            "preferences",
            "preferences.approved",
        ),
        (
            config.preferences.full_time_start is not None,
            "missing_start_date",
            "A full-time availability start date is required.",
            "preferences",
            "preferences.full_time_start",
        ),
        (
            config.manifest.validation.legal_status_approved,
            "manifest_legal_status_not_approved",
            "Legal status requires explicit approval.",
            "legal",
            "manifest.validation.legal_status_approved",
        ),
        (
            config.legal_status.work_authorization_confirmed,
            "unconfirmed_work_authorization",
            "Work authorization must be confirmed.",
            "legal",
            "legal_status.work_authorization_confirmed",
        ),
        (
            config.legal_status.approved_for_automated_use,
            "legal_status_not_approved",
            "Legal status is not approved for automated use.",
            "legal",
            "legal_status.approved_for_automated_use",
        ),
        (
            config.legal_status.approved,
            "legal_status_item_not_approved",
            "Legal status requires explicit candidate approval.",
            "legal",
            "legal_status.approved",
        ),
        (
            config.legal_status.last_verified is not None,
            "legal_status_not_verified",
            "Legal status needs a candidate-provided verification date.",
            "legal",
            "legal_status.last_verified",
        ),
        (
            config.manifest.validation.automatic_answers_approved,
            "automatic_answers_not_approved",
            "Automatic answers require explicit approval.",
            "answers",
            "manifest.validation.automatic_answers_approved",
        ),
        (
            config.cv_rules.approved and config.cover_letter_rules.approved,
            "document_rules_not_approved",
            "CV and cover-letter rules require explicit candidate approval.",
            "documents",
            "cv_rules.approved",
        ),
        (
            config.manifest.validation.cv_templates_approved,
            "cv_templates_not_approved",
            "CV templates require explicit approval.",
            "documents",
            "manifest.validation.cv_templates_approved",
        ),
    )
    for passed, code, message, domain, field_path in checks:
        if not passed:
            issues.append(_issue(code, message, domain, field_path))

    for index, answer in enumerate(config.approved_answers.items):
        if answer.sensitive and (not answer.approved or not answer.auto_submit_allowed):
            issues.append(
                _issue(
                    "sensitive_answer_not_approved",
                    "Sensitive answers require explicit approval and auto-submit permission.",
                    "answers",
                    f"approved_answers.items[{index}]",
                )
            )
        if answer.valid_until is not None and answer.valid_until < date.today():
            issues.append(
                _issue(
                    "approved_answer_expired",
                    "An approved answer has expired and cannot be used.",
                    "answers",
                    f"approved_answers.items[{index}].valid_until",
                )
            )

    evidence_fact_collections = (
        ("experience", tuple(item.achievements for item in config.experience.items)),
        ("projects", tuple(item.outcomes for item in config.projects.items)),
    )
    for collection_name, fact_collections in evidence_fact_collections:
        for item_index, facts in enumerate(fact_collections):
            for fact_index, fact in enumerate(facts):
                if isinstance(fact, ClaimFact) and fact.approved and not fact.verified:
                    issues.append(
                        _issue(
                            "unverified_approved_claim",
                            "An approved claim must be verified before external use.",
                            "evidence",
                            f"{collection_name}.items[{item_index}].facts[{fact_index}]",
                        )
                    )

    domains = (
        _domain("profile", "Profile approval", "manifest", True, issues),
        _domain("identity", "Identity", "identity", bool(config.identity.full_name), issues),
        _domain("biography", "Biography", "biography", bool(config.biography.summary), issues),
        _domain(
            "evidence",
            "Experience and projects",
            "experience",
            approved_evidence,
            issues,
        ),
        _domain("skills", "Skills", "skills", bool(config.skills.categories), issues),
        _domain("languages", "Languages", "languages", approved_languages, issues),
        _domain(
            "strategy",
            "Career strategy",
            "career_strategy",
            bool(config.career_strategy.target_roles),
            issues,
        ),
        _domain(
            "preferences",
            "Preferences and salary",
            "preferences",
            bool(config.preferences.locations),
            issues,
        ),
        _domain(
            "legal",
            "Legal and work authorization",
            "legal_status",
            bool(config.legal_status.jurisdictions),
            issues,
        ),
        _domain(
            "answers",
            "Approved answers",
            "approved_answers",
            bool(config.approved_answers.items),
            issues,
        ),
        _domain(
            "documents",
            "Document rules",
            "cv_rules",
            bool(config.cv_rules.allowed_sections),
            issues,
        ),
        _domain(
            "certifications",
            "Certifications",
            "certifications",
            config.manifest.data_files.certifications is not None,
            issues,
        ),
        _domain(
            "publications",
            "Publications",
            "publications",
            config.manifest.data_files.publications is not None,
            issues,
        ),
        _domain(
            "notifications",
            "Notification rules",
            "notification_rules",
            config.manifest.data_files.notification_rules is not None,
            issues,
        ),
    )
    capabilities = (
        _capability(
            "discovery",
            "Discovery",
            ("profile", "strategy", "preferences"),
            domains,
            None if config.manifest.workflow.discovery_enabled else "discovery_disabled",
        ),
        _capability(
            "job_analysis",
            "Job analysis",
            ("profile", "evidence", "skills", "languages", "strategy", "preferences"),
            domains,
        ),
        _capability(
            "document_generation",
            "Document generation",
            ("profile", "identity", "biography", "evidence", "skills", "documents"),
            domains,
        ),
        _capability(
            "assisted_form_filling",
            "Assisted form filling",
            ("profile", "identity", "legal", "answers"),
            domains,
        ),
        _capability(
            "controlled_submission",
            "Controlled submission",
            ("profile", "identity", "legal", "answers", "documents"),
            domains,
        ),
        _capability(
            "autonomous_submission",
            "Autonomous submission",
            ("profile", "identity", "legal", "answers", "documents"),
            domains,
            None
            if config.manifest.workflow.automatic_submission_enabled
            else "automatic_submission_disabled",
        ),
        _capability(
            "email_tracking",
            "Email tracking",
            ("profile",),
            domains,
            None if config.manifest.workflow.email_tracking_enabled else "email_tracking_disabled",
        ),
    )
    return ReadinessReport(
        candidate_id=config.manifest.candidate_id,
        status="ready" if not issues else "not_ready",
        issues=tuple(issues),
        domains=domains,
        capabilities=capabilities,
    )
