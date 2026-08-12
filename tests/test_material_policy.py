from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.applications import ApplicationConflictError, ApplicationService
from app.applications.contracts import MaterialRevisionRequest
from app.candidates.models import CandidateConfig, ClaimFact
from app.candidates.service import CandidateService
from app.db import build_session_factory
from app.discovery.verification import StoredFixtureJobSourceVerifier
from app.domain.enums import DocumentKind
from app.domain.models import Application, Base, CandidateJobScore, GlobalJob, JobVersion
from app.job_service import DiscoveryRequest, JobService
from app.materials.generation import DeterministicMaterialGenerator
from app.materials.validation import MaterialValidator

_CANDIDATE_ID = "example_candidate"


def _service(candidates_root: Path) -> ApplicationService:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return ApplicationService(
        build_session_factory(engine),
        CandidateService(candidates_root),
        candidates_root.parent / "runtime",
        source_verifier=StoredFixtureJobSourceVerifier(),
    )


def _job(*, title: str, description: str, company: str = "Neutral Example Ltd") -> GlobalJob:
    return GlobalJob(
        source="fixture",
        external_id=f"policy-{title.casefold().replace(' ', '-')}",
        company=company,
        title=title,
        normalized_title=title,
        description=description,
        description_normalized=description,
        url="https://boards.greenhouse.io/fictional/jobs/material-policy",
        application_url="https://boards.greenhouse.io/fictional/jobs/material-policy",
        required_skills=["Python", "Machine Learning"],
        preferred_skills=["Docker"],
        raw_payload={},
    )


def _claim(claim_id: str, statement: str) -> ClaimFact:
    return ClaimFact(
        id=claim_id,
        statement=statement,
        verified=True,
        source="fictional policy evidence",
        publicly_usable=True,
        confidentiality="public",
        approved=True,
    )


def _policy_config(candidates_root: Path) -> CandidateConfig:
    config = CandidateService(candidates_root).get_config(_CANDIDATE_ID)
    seed_experience = config.experience.items[0]
    seed_project = config.projects.items[0]
    ml_experience = seed_experience.model_copy(
        update={
            "id": "experience_ml_policy",
            "title": "Machine Learning Engineer",
            "skills": ("Python", "Machine Learning", "Docker"),
            "domains": ("Machine learning",),
            "role_categories": ("Machine Learning Engineer",),
            "achievements": (
                _claim(
                    "experience_ml_policy_claim",
                    "Built a fictional machine-learning evaluation service in Python",
                ),
            ),
        }
    )
    unrelated_experience = seed_experience.model_copy(
        update={
            "id": "experience_unrelated_policy",
            "title": "Retail Operations Associate",
            "skills": ("Inventory",),
            "domains": ("Retail",),
            "role_categories": ("Retail Operations",),
            "achievements": (
                _claim(
                    "experience_unrelated_policy_claim",
                    "Documented a fictional retail inventory process",
                ),
            ),
        }
    )
    ml_project = seed_project.model_copy(
        update={
            "id": "project_ml_policy",
            "name": "Fictional Model Evaluation",
            "description": (
                "A fictional Python machine-learning evaluation service using PyTorch and "
                "Kubernetes feature stores."
            ),
            "skills": (
                "Python",
                "Machine Learning",
                "Docker",
                "PyTorch",
                "Kubernetes",
                "Feature Stores",
            ),
            "domains": ("Machine learning",),
            "role_categories": ("Machine Learning Engineer",),
            "outcomes": (
                _claim(
                    "project_ml_policy_claim",
                    "Produced fictional reproducible machine-learning reports",
                ),
            ),
        }
    )
    unrelated_project = seed_project.model_copy(
        update={
            "id": "project_unrelated_policy",
            "name": "Fictional Retail Catalogue",
            "description": "A fictional catalogue for retail inventory.",
            "skills": ("Inventory",),
            "domains": ("Retail",),
            "role_categories": ("Retail Operations",),
            "outcomes": (
                _claim(
                    "project_unrelated_policy_claim",
                    "Catalogued fictional retail inventory records",
                ),
            ),
        }
    )
    return config.model_copy(
        update={
            "experience": config.experience.model_copy(
                update={
                    "items": (seed_experience, unrelated_experience, ml_experience),
                }
            ),
            "projects": config.projects.model_copy(
                update={"items": (seed_project, unrelated_project, ml_project)}
            ),
            "cv_rules": config.cv_rules.model_copy(
                update={
                    "max_experiences": 1,
                    "max_projects": 1,
                    "template_by_role": {
                        "Machine Learning Engineer": "technical_two_page",
                        "Backend Engineer": "technical_single_page",
                    },
                }
            ),
            "cover_letter_rules": config.cover_letter_rules.model_copy(
                update={
                    "generation_mode": "priority_only",
                    "min_words": 100,
                    "max_words": 400,
                    "max_experiences": 1,
                    "max_projects": 1,
                }
            ),
        }
    )


def test_relevance_caps_and_conditional_cover_letter_policy(
    copied_candidates_root: Path,
) -> None:
    service = _service(copied_candidates_root)
    config = _policy_config(copied_candidates_root)
    request = service._generation_request(
        config,
        uuid4(),
        _job(
            title="Machine Learning Engineer",
            description=(
                "Build Python machine-learning services with Docker, PyTorch, Kubernetes, "
                "and feature stores."
            ),
        ),
    )

    assert request.selected_experience_ids == ("experience_ml_policy",)
    assert request.selected_project_ids == ("project_ml_policy",)
    assert request.cv_template_id == "technical_two_page"
    assert request.requested_documents == (DocumentKind.CV, DocumentKind.COVER_LETTER)
    assert request.cover_letter_reason == "priority_role"

    omitted = service._generation_request(
        config,
        uuid4(),
        _job(
            title="Retail Support Associate",
            description="Maintain a fictional retail catalogue.",
        ),
    )
    assert omitted.requested_documents == (DocumentKind.CV,)
    assert omitted.cover_letter_reason is None

    cv_fact_ids = {
        fact.fact_id for fact in request.approved_facts if DocumentKind.CV in fact.document_kinds
    }
    assert "experience_ml_policy_claim" in cv_fact_ids
    assert "project_ml_policy_claim" in cv_fact_ids
    assert "experience_unrelated_policy_claim" not in cv_fact_ids
    assert "project_unrelated_policy_claim" not in cv_fact_ids


def test_role_template_override_is_selected_deterministically(
    copied_candidates_root: Path,
) -> None:
    service = _service(copied_candidates_root)
    config = _policy_config(copied_candidates_root)
    request = service._generation_request(
        config,
        uuid4(),
        _job(
            title="Backend Engineer",
            description="Build typed Python APIs and automated tests.",
        ),
    )

    assert request.cv_template_id == "technical_single_page"
    assert request.selected_experience_ids == ("experience_example_1",)


def test_cover_letter_respects_word_bounds_and_exact_claim_provenance(
    copied_candidates_root: Path,
) -> None:
    service = _service(copied_candidates_root)
    request = service._generation_request(
        _policy_config(copied_candidates_root),
        uuid4(),
        _job(
            title="Machine Learning Engineer",
            description=(
                "Build Python machine-learning services with Docker, PyTorch, Kubernetes, "
                "and feature stores."
            ),
        ),
    )
    result = DeterministicMaterialGenerator().generate(request)
    cover_letter = next(
        document for document in result.documents if document.kind is DocumentKind.COVER_LETTER
    )
    word_count = len(cover_letter.content.split())

    assert request.cover_letter_min_words <= word_count <= request.cover_letter_max_words
    assert cover_letter.minimum_words == request.cover_letter_min_words
    assert cover_letter.maximum_words == request.cover_letter_max_words
    approved = {fact.fact_id: fact.text for fact in request.approved_facts}
    assert cover_letter.claims
    assert all(
        len(claim.evidence_ids) == 1
        and approved[claim.evidence_ids[0]] == claim.text
        and claim.text in cover_letter.content
        for claim in cover_letter.claims
    )
    assert MaterialValidator().validate(result).valid

    default_bounded = request.model_copy(
        update={"cover_letter_min_words": 250, "cover_letter_max_words": 400}
    )
    default_cover = next(
        document
        for document in DeterministicMaterialGenerator().generate(default_bounded).documents
        if document.kind is DocumentKind.COVER_LETTER
    )
    assert 250 <= len(default_cover.content.split()) <= 400

    below = cover_letter.model_copy(update={"minimum_words": word_count + 1})
    above = cover_letter.model_copy(update={"maximum_words": word_count - 1})
    assert {
        issue.code
        for issue in MaterialValidator()
        .validate(result.model_copy(update={"documents": (below,)}))
        .issues
    } == {"document_below_minimum_words"}
    assert {
        issue.code
        for issue in MaterialValidator()
        .validate(result.model_copy(update={"documents": (above,)}))
        .issues
    } == {"document_above_maximum_words"}


def _integrated_services(
    candidates_root: Path, runtime_root: Path
) -> tuple[JobService, ApplicationService, sessionmaker[Session]]:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(candidates_root)
    verifier = StoredFixtureJobSourceVerifier()
    return (
        JobService(sessions, candidates, verifier),
        ApplicationService(sessions, candidates, runtime_root, source_verifier=verifier),
        sessions,
    )


def test_material_policy_and_selected_ids_are_persisted(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    scoring_path = copied_candidates_root / _CANDIDATE_ID / "scoring_rules.json"
    scoring = json.loads(scoring_path.read_text(encoding="utf-8"))
    scoring["application_threshold"] = 40
    scoring["human_review_threshold"] = 30
    scoring_path.write_text(json.dumps(scoring), encoding="utf-8")
    jobs, applications, sessions = _integrated_services(
        copied_candidates_root, tmp_path / "runtime"
    )
    discovered = jobs.discover(
        DiscoveryRequest(
            candidate_id=_CANDIDATE_ID,
            platform="greenhouse",
            company="Fictional Robotics Ltd",
            company_domain="fictional-robotics.invalid",
            payloads=(
                {
                    "id": 8201,
                    "internal_job_id": "REQ-MATERIAL-POLICY-8201",
                    "title": "Machine Learning Engineer",
                    "content": "Build truthful synthetic machine-learning services in Python.",
                    "location": {"name": "Exampleton"},
                    "absolute_url": "https://boards.greenhouse.io/fictional/jobs/8201",
                },
            ),
        ),
        "discover-material-policy-8201",
    )
    job_id = discovered.job_ids[0]
    jobs.analyze(_CANDIDATE_ID, job_id, "analyze-material-policy-8201")
    detail = applications.generate_materials(_CANDIDATE_ID, job_id, "generate-material-policy-8201")

    with sessions() as session:
        bound_job_version = session.scalar(select(JobVersion).where(JobVersion.job_id == job_id))
        assert bound_job_version is not None

    expected_policy = {
        "schema_version": "1.0",
        "generator_version": "deterministic_material_v2",
        "job_version": bound_job_version.version,
        "job_payload_sha256": bound_job_version.payload_sha256,
        "cv_template_id": "technical_two_page",
        "cv_template_version": "1.0",
        "selected_experience_ids": ["experience_example_1"],
        "selected_project_ids": ["project_example_1"],
        "cover_letter": {
            "included": True,
            "reason": "candidate_requested",
            "selected_experience_ids": ["experience_example_1"],
            "selected_project_ids": ["project_example_1"],
            "minimum_words": 100,
            "maximum_words": 400,
        },
    }
    assert detail.material_policy is not None
    assert detail.material_policy.model_dump(mode="json") == expected_policy

    with sessions() as session:
        application = session.scalar(
            select(Application).where(Application.id == detail.application_id)
        )
        assert application is not None and application.material_policy == expected_policy
        score = session.scalar(
            select(CandidateJobScore).where(
                CandidateJobScore.candidate_id == _CANDIDATE_ID,
                CandidateJobScore.job_id == job_id,
            )
        )
        assert score is not None
        assert score.rationale["selected_experience"] == ["experience_example_1"]
        assert score.rationale["selected_projects"] == ["project_example_1"]
        assert score.rationale["material_policy"] == expected_policy

    job = jobs.get_job(_CANDIDATE_ID, job_id)
    assert job.selected_experience == ("experience_example_1",)
    assert job.selected_projects == ("project_example_1",)

    jobs.discover(
        DiscoveryRequest(
            candidate_id=_CANDIDATE_ID,
            platform="greenhouse",
            company="Fictional Robotics Ltd",
            company_domain="fictional-robotics.invalid",
            payloads=(
                {
                    "id": 8201,
                    "internal_job_id": "REQ-MATERIAL-POLICY-8201",
                    "title": "Machine Learning Platform Engineer",
                    "content": "Changed source evidence for a fictional platform role.",
                    "location": {"name": "Exampleton"},
                    "absolute_url": "https://boards.greenhouse.io/fictional/jobs/8201",
                },
            ),
        ),
        "rediscover-material-policy-8201",
    )
    cv = next(document for document in detail.documents if document.kind == "cv")
    revised_content = "\n\n".join(cv.content.split("\n\n")[:-1])
    with pytest.raises(ApplicationConflictError, match="original unchanged job snapshot"):
        applications.revise_material(
            _CANDIDATE_ID,
            detail.application_id,
            MaterialRevisionRequest(
                document_id=cv.document_id,
                base_version=cv.version,
                content=revised_content,
            ),
            "revision-after-job-drift-8201",
        )

    with sessions.begin() as session:
        application = session.get(Application, detail.application_id)
        assert application is not None
        application.material_policy = {}
    with sessions() as session:
        application = session.get(Application, detail.application_id)
        assert application is not None
        with pytest.raises(ApplicationConflictError, match="policy is missing or invalid"):
            applications._cover_letter_included(application)
