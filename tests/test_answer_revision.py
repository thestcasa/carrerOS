from __future__ import annotations

import json
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, event, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.applications import (
    AnswerRevisionRequest,
    ApplicationConflictError,
    ApplicationDetail,
    ApplicationService,
)
from app.candidates.service import CandidateService
from app.db import build_session_factory
from app.discovery.verification import StoredFixtureJobSourceVerifier
from app.domain.enums import ApplicationState
from app.domain.models import AgentReview, ApplicationAnswer, Base, CandidateDeletionRecord
from app.job_service import DiscoveryRequest, JobService
from app.materials import DeterministicMaterialGenerator
from app.materials.contracts import GenerationRequest, GenerationResult


class _ForgedAnswerGenerator(DeterministicMaterialGenerator):
    def generate(self, request: GenerationRequest) -> GenerationResult:
        result = super().generate(request)
        first = result.answers[0].model_copy(
            update={
                "answer": "Fabricated legal answer",
                "approved_source_key": "sponsorship",
                "evidence_ids": ("fabricated_evidence",),
                "supported": True,
            }
        )
        return result.model_copy(update={"answers": (first, *result.answers[1:])})


def _services(
    candidates_root: Path,
    runtime_root: Path,
    *,
    database_url: str | None = None,
) -> tuple[JobService, ApplicationService, sessionmaker[Session]]:
    engine = create_engine(database_url or "sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    if database_url is None:
        Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(candidates_root)
    verifier = StoredFixtureJobSourceVerifier()
    return (
        JobService(sessions, candidates, verifier),
        ApplicationService(sessions, candidates, runtime_root, source_verifier=verifier),
        sessions,
    )


def _lower_threshold(candidates_root: Path) -> None:
    path = candidates_root / "example_candidate" / "scoring_rules.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["application_threshold"] = 40
    data["human_review_threshold"] = 30
    path.write_text(json.dumps(data), encoding="utf-8")


def _generated(
    candidates_root: Path,
    runtime_root: Path,
    external_id: int,
    *,
    database_url: str | None = None,
    forged_generator: bool = False,
) -> tuple[ApplicationService, sessionmaker[Session], ApplicationDetail]:
    _lower_threshold(candidates_root)
    jobs, applications, sessions = _services(
        candidates_root, runtime_root, database_url=database_url
    )
    if forged_generator:
        applications._generator = _ForgedAnswerGenerator()
    discovered = jobs.discover(
        DiscoveryRequest(
            candidate_id="example_candidate",
            platform="greenhouse",
            company="Fictional Robotics Ltd",
            company_domain="fictional-robotics.invalid",
            payloads=(
                {
                    "id": external_id,
                    "internal_job_id": f"REQ-ANSWER-{external_id}",
                    "title": "Machine Learning Engineer",
                    "content": "Build truthful synthetic machine-learning services.",
                    "location": {"name": "Exampleton"},
                    "absolute_url": (f"https://boards.greenhouse.io/fictional/jobs/{external_id}"),
                },
            ),
        ),
        f"discover-answer-{external_id}",
    )
    job_id = discovered.job_ids[0]
    jobs.analyze("example_candidate", job_id, f"analyze-answer-{external_id}")
    generated = applications.generate_materials(
        "example_candidate", job_id, f"generate-answer-{external_id}"
    )
    return applications, sessions, generated


def test_answer_revision_appends_history_and_recovery_rebinds_review(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    applications, sessions, generated = _generated(
        copied_candidates_root, tmp_path / "runtime", 8201
    )
    original = next(answer for answer in generated.answers if answer.question_key == "sponsorship")
    unsupported_request = AnswerRevisionRequest(
        answer_id=original.answer_id,
        base_version=original.version,
        answer="Human review is required before I can answer.",
        reason="The generated legal answer needs review.",
    )

    unsupported = applications.revise_answer(
        "example_candidate",
        generated.application_id,
        unsupported_request,
        "revise-answer-8201-unsupported",
    )
    replay = applications.revise_answer(
        "example_candidate",
        generated.application_id,
        unsupported_request,
        "revise-answer-8201-unsupported",
    )

    assert replay == unsupported
    assert unsupported.state is ApplicationState.REVIEW_FAILED
    versions = [answer for answer in unsupported.answers if answer.question_key == "sponsorship"]
    assert [answer.version for answer in versions] == [1, 2]
    assert versions[0].answer == "No" and versions[0].immutable
    assert versions[1].answer == unsupported_request.answer
    assert not versions[1].supported and not versions[1].immutable
    assert versions[1].revision_actor == "local-user"
    assert versions[1].base_answer_id == original.answer_id
    assert versions[1].reason == unsupported_request.reason
    assert versions[1].candidate_snapshot_id == original.candidate_snapshot_id
    assert versions[1].sha256 != versions[0].sha256
    with pytest.raises(ApplicationConflictError, match="did not pass"):
        applications.approve_materials(
            "example_candidate", generated.application_id, "approve-unsupported-answer-8201"
        )

    recovered = applications.revise_answer(
        "example_candidate",
        generated.application_id,
        AnswerRevisionRequest(
            answer_id=versions[1].answer_id,
            base_version=2,
            answer="No",
            reason="Restore the exact snapshot-approved answer.",
        ),
        "revise-answer-8201-recover",
    )
    assert recovered.state is ApplicationState.REVIEW_PENDING
    latest = [answer for answer in recovered.answers if answer.question_key == "sponsorship"][-1]
    assert latest.version == 3
    assert latest.supported
    assert latest.approved_source_key == "sponsorship"
    assert recovered.review is not None and recovered.review.semantic_passed
    answer_reports = cast(list[dict[str, object]], recovered.review.report["answer_reports"])
    sponsorship_report = next(
        report for report in answer_reports if report["question_key"] == "sponsorship"
    )
    assert sponsorship_report == {
        "answer_id": str(latest.answer_id),
        "question_key": "sponsorship",
        "version": 3,
        "sha256": latest.sha256,
        "candidate_snapshot_id": str(latest.candidate_snapshot_id),
    }
    applications.approve_materials(
        "example_candidate", generated.application_id, "approve-recovered-answer-8201"
    )
    with pytest.raises(ApplicationConflictError, match="review is pending or failed"):
        applications.revise_answer(
            "example_candidate",
            generated.application_id,
            AnswerRevisionRequest(
                answer_id=latest.answer_id,
                base_version=3,
                answer="A post-approval edit must fail.",
            ),
            "revise-answer-after-approval-8201",
        )
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count(ApplicationAnswer.id)).where(
                    ApplicationAnswer.application_id == generated.application_id,
                    ApplicationAnswer.question_key == "sponsorship",
                )
            )
            == 3
        )
        assert (
            session.scalar(
                select(func.count(AgentReview.id)).where(
                    AgentReview.application_id == generated.application_id
                )
            )
            == 3
        )


def test_answer_revision_rejects_stale_noop_and_unreviewed_append(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    applications, sessions, generated = _generated(
        copied_candidates_root, tmp_path / "runtime", 8202
    )
    original = next(
        answer for answer in generated.answers if answer.question_key == "work_authorization"
    )
    with pytest.raises(ApplicationConflictError, match="must change"):
        applications.revise_answer(
            "example_candidate",
            generated.application_id,
            AnswerRevisionRequest(
                answer_id=original.answer_id,
                base_version=1,
                answer=original.answer,
            ),
            "revise-answer-noop-8202",
        )
    revised = applications.revise_answer(
        "example_candidate",
        generated.application_id,
        AnswerRevisionRequest(
            answer_id=original.answer_id,
            base_version=1,
            answer="Not yet verified.",
        ),
        "revise-answer-once-8202",
    )
    with pytest.raises(ApplicationConflictError, match="base version is stale"):
        applications.revise_answer(
            "example_candidate",
            generated.application_id,
            AnswerRevisionRequest(
                answer_id=original.answer_id,
                base_version=1,
                answer="Another edit.",
            ),
            "revise-answer-stale-8202",
        )

    latest = next(
        answer
        for answer in revised.answers
        if answer.question_key == "work_authorization" and answer.version == 2
    )
    with sessions.begin() as session:
        session.add(
            ApplicationAnswer(
                candidate_id="example_candidate",
                application_id=generated.application_id,
                question_key=latest.question_key,
                question=latest.question,
                answer="Yes",
                version=3,
                sha256="0" * 64,
                actor_id="unreviewed-writer",
                revision_kind="manual",
                previous_answer_id=latest.answer_id,
                candidate_snapshot_id=latest.candidate_snapshot_id,
                candidate_snapshot_version=latest.candidate_snapshot_version,
                candidate_snapshot_sha256=latest.candidate_snapshot_sha256,
                approved_source_key="work_authorization",
                evidence_ids={"items": []},
                supported=True,
            )
        )
    with pytest.raises(ApplicationConflictError, match=r"did not pass|answer identity"):
        applications.approve_materials(
            "example_candidate", generated.application_id, "approve-unreviewed-answer-8202"
        )


def test_generation_rederives_answer_provenance_instead_of_trusting_generator(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    _applications, _sessions, generated = _generated(
        copied_candidates_root,
        tmp_path / "runtime",
        8205,
        forged_generator=True,
    )
    forged = next(
        answer for answer in generated.answers if answer.answer == "Fabricated legal answer"
    )
    assert generated.state is ApplicationState.REVIEW_FAILED
    assert not forged.supported
    assert forged.approved_source_key is None
    assert forged.evidence_ids == ()


def test_regeneration_appends_withdrawal_without_resurrecting_removed_prompt(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    applications, sessions, generated = _generated(
        copied_candidates_root, tmp_path / "runtime", 8203
    )
    sponsorship = next(
        answer for answer in generated.answers if answer.question_key == "sponsorship"
    )
    failed = applications.revise_answer(
        "example_candidate",
        generated.application_id,
        AnswerRevisionRequest(
            answer_id=sponsorship.answer_id,
            base_version=1,
            answer="Needs manual legal review.",
        ),
        "revise-answer-before-withdrawal-8203",
    )
    assert failed.state is ApplicationState.REVIEW_FAILED
    answers_path = copied_candidates_root / "example_candidate" / "approved_answers.json"
    answers_data = json.loads(answers_path.read_text(encoding="utf-8"))
    answers_data["items"] = [item for item in answers_data["items"] if item["key"] != "sponsorship"]
    answers_path.write_text(json.dumps(answers_data), encoding="utf-8")
    profile_path = copied_candidates_root / "example_candidate" / "profile.yaml"
    profile_path.write_text(
        profile_path.read_text(encoding="utf-8").replace(
            'profile_version: "1.0.0"', 'profile_version: "1.0.1"'
        ),
        encoding="utf-8",
    )

    regenerated = applications.generate_materials(
        "example_candidate", generated.job_id, "regenerate-withdrawn-answer-8203"
    )
    assert regenerated.state is ApplicationState.REVIEW_PENDING
    sponsorship_history = [
        answer for answer in regenerated.answers if answer.question_key == "sponsorship"
    ]
    assert [answer.version for answer in sponsorship_history] == [1, 2, 3]
    assert sponsorship_history[-1].revision_kind == "withdrawn"
    assert sponsorship_history[-1].immutable
    assert regenerated.review is not None and regenerated.review.semantic_passed
    reports = cast(list[dict[str, object]], regenerated.review.report["answer_reports"])
    assert {report["question_key"] for report in reports} == {"work_authorization"}
    with sessions() as session:
        latest_sponsorship = session.scalar(
            select(ApplicationAnswer)
            .where(
                ApplicationAnswer.application_id == generated.application_id,
                ApplicationAnswer.question_key == "sponsorship",
            )
            .order_by(ApplicationAnswer.version.desc())
            .limit(1)
        )
        assert latest_sponsorship is not None
        assert latest_sponsorship.revision_kind == "withdrawn"


def test_migrated_answer_rows_are_database_append_only(
    copied_candidates_root: Path, tmp_path: Path, project_root: Path
) -> None:
    database_path = tmp_path / "answers.db"
    database_url = f"sqlite+pysqlite:///{database_path}"
    config = Config(project_root / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    _applications, sessions, generated = _generated(
        copied_candidates_root,
        tmp_path / "runtime",
        8204,
        database_url=database_url,
    )
    answer = generated.answers[0]
    with pytest.raises(IntegrityError, match="append-only"), sessions.begin() as session:
        session.execute(
            update(ApplicationAnswer)
            .where(ApplicationAnswer.id == answer.answer_id)
            .values(answer="mutated")
        )
    with pytest.raises(IntegrityError, match="append-only"), sessions.begin() as session:
        session.execute(delete(ApplicationAnswer).where(ApplicationAnswer.id == answer.answer_id))
    with sessions.begin() as session:
        session.add(
            CandidateDeletionRecord(
                candidate_id="example_candidate",
                idempotency_key_sha256="a" * 64,
                request_sha256="a" * 64,
                status="deleting",
            )
        )
    with sessions.begin() as session:
        session.execute(
            delete(ApplicationAnswer).where(ApplicationAnswer.candidate_id == "example_candidate")
        )
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count(ApplicationAnswer.id)).where(
                    ApplicationAnswer.candidate_id == "example_candidate"
                )
            )
            == 0
        )


def test_migration_backfills_legacy_answer_identity(
    copied_candidates_root: Path, tmp_path: Path, project_root: Path
) -> None:
    database_path = tmp_path / "legacy-answers.db"
    database_url = f"sqlite+pysqlite:///{database_path}"
    config = Config(project_root / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "4e8b1c2d3f40")
    engine = create_engine(database_url)
    now = "2026-08-06 12:00:00"
    job_id = "1" * 32
    application_id = "2" * 32
    answer_id = "3" * 32
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO global_jobs (
                    id, source, external_id, company, title, description, url, raw_payload,
                    first_seen_at, created_at, updated_at
                ) VALUES (
                    :id, 'fixture', 'legacy-answer', 'Example Co', 'Example Role',
                    'Example description', 'https://example.invalid/job', '{}', :now, :now, :now
                )
                """
            ),
            {"id": job_id, "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO applications (
                    id, job_id, state, outcome, retry_count, created_at, updated_at,
                    candidate_id, duplicate_hash, submission_identity_hash
                ) VALUES (
                    :id, :job_id, 'REVIEW_PENDING', 'PENDING', 0, :now, :now,
                    'example_candidate', :duplicate_hash, :submission_hash
                )
                """
            ),
            {
                "id": application_id,
                "job_id": job_id,
                "now": now,
                "duplicate_hash": "4" * 64,
                "submission_hash": "5" * 64,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO application_answers (
                    id, application_id, question_key, question, answer, approved_source_key,
                    evidence_ids, supported, created_at, updated_at, candidate_id
                ) VALUES (
                    :id, :application_id, 'legal_answer', 'A legal question?', 'Legacy answer',
                    NULL, '{}', 1, :now, :now, 'example_candidate'
                )
                """
            ),
            {"id": answer_id, "application_id": application_id, "now": now},
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT version, sha256, actor_id, revision_kind, supported,
                       candidate_snapshot_id
                FROM application_answers WHERE id = :id
                """
            ),
            {"id": answer_id},
        ).one()
    assert row.version == 1
    assert row.sha256 == ApplicationService._answer_sha256("Legacy answer")
    assert row.actor_id == "legacy-answer-unknown"
    assert row.revision_kind == "legacy_unknown"
    assert row.supported == 0
    assert row.candidate_snapshot_id is None
    sessions = build_session_factory(engine)
    applications = ApplicationService(
        sessions,
        CandidateService(copied_candidates_root),
        tmp_path / "legacy-runtime",
        source_verifier=StoredFixtureJobSourceVerifier(),
    )
    detail = applications.get_application(
        "example_candidate", UUID("22222222-2222-2222-2222-222222222222")
    )
    assert detail.answers[0].revision_kind == "legacy_unknown"
    assert detail.answers[0].immutable
