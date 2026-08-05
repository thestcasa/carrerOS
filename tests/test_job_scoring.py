from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.candidates.loader import CandidateLoader
from app.jobs.scoring import NormalizedJob, RequiredLanguage, RoleClassification, evaluate_job


def _job(**overrides: object) -> NormalizedJob:
    values: dict[str, object] = {
        "job_id": "fictional-job-1",
        "company": "Example Robotics Ltd",
        "title": "Machine Learning Engineer",
        "description": "Build reliable machine-learning services with Python and SQL.",
        "location": "Exampleton",
        "work_mode": "hybrid",
        "employment_type": "permanent",
        "domain": "Responsible AI",
        "required_skills": ("Python", "SQL"),
        "preferred_skills": ("Docker",),
        "salary_min": 100_000,
        "salary_max": 130_000,
        "salary_currency": "USD",
    }
    values.update(overrides)
    return NormalizedJob.model_validate(values)


def test_target_job_uses_configured_weights_and_exposes_evidence(
    example_candidates_root: Path,
) -> None:
    config = CandidateLoader(example_candidates_root).load("example_candidate")

    result = evaluate_job(_job(), config)

    assert result.classification is RoleClassification.TARGET
    assert result.total_score == 100
    assert result.proposed_action == "prepare"
    assert result.hard_blockers == ()
    assert {item.name: item.weight for item in result.dimensions} == config.scoring_rules.weights
    assert "skill:python" in result.evidence
    assert all(item.explanation for item in result.dimensions)


def test_salary_location_language_company_and_role_rules_block_deterministically(
    example_candidates_root: Path,
) -> None:
    config = CandidateLoader(example_candidates_root).load("example_candidate")
    job = _job(
        company="Example Gambling Holdings",
        title="Unpaid Intern",
        domain="Gambling",
        location="Elsewhere",
        work_mode="onsite",
        employment_type="internship",
        salary_max=50_000,
        required_languages=(RequiredLanguage(language="Spanish", minimum_level="C1"),),
    )

    result = evaluate_job(job, config)

    assert result.proposed_action == "skip"
    assert set(result.hard_blockers) == {
        "company_blocked",
        "role_blocked",
        "domain_excluded",
        "employment_type_incompatible",
        "location_incompatible",
        "salary_below_minimum",
        "language_incompatible:spanish",
    }


def test_same_job_scores_differently_for_candidate_configuration(
    example_candidates_root: Path,
) -> None:
    alpha = CandidateLoader(example_candidates_root).load("example_candidate")
    beta = alpha.model_copy(
        update={
            "manifest": alpha.manifest.model_copy(update={"candidate_id": "candidate_beta"}),
            "identity": alpha.identity.model_copy(update={"candidate_id": "candidate_beta"}),
            "career_strategy": alpha.career_strategy.model_copy(
                update={"target_roles": ("Frontend Engineer",), "priority_domains": ("Commerce",)}
            ),
            "roles": alpha.roles.model_copy(update={"target": ("Frontend Engineer",)}),
            "skills": alpha.skills.model_copy(
                update={"categories": {"engineering": ("TypeScript", "React")}}
            ),
            "scoring_rules": alpha.scoring_rules.model_copy(
                update={
                    "weights": {
                        "role_alignment": Decimal("0.50"),
                        "skills_alignment": Decimal("0.50"),
                    }
                }
            ),
        }
    )

    alpha_result = evaluate_job(_job(), alpha)
    beta_result = evaluate_job(_job(), beta)

    assert alpha_result.total_score == 100
    assert beta_result.total_score == 0
    assert alpha_result.classification is RoleClassification.TARGET
    assert beta_result.classification is RoleClassification.NON_TARGET
