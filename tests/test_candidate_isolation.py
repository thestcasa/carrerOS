from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.enums import ApplicationState, DocumentKind
from app.domain.models import (
    Application,
    ApplicationDocument,
    Base,
    CandidateJobScore,
    GlobalJob,
)


def _isolated_engine() -> Engine:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def test_every_candidate_owned_table_has_candidate_id() -> None:
    candidate_neutral_tables = {"global_jobs", "job_versions"}
    for table_name, table in Base.metadata.tables.items():
        if table_name not in candidate_neutral_tables:
            assert "candidate_id" in table.columns, f"{table_name} is missing candidate_id"
            assert table.columns["candidate_id"].nullable is False


def test_candidate_job_scores_are_query_isolated() -> None:
    engine = _isolated_engine()
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        job = GlobalJob(
            source="fictional-board",
            external_id="job-1",
            company="Example Robotics Ltd",
            title="Backend Engineer",
            description="Fictional role",
            url="https://example.invalid/jobs/1",
        )
        session.add(job)
        session.flush()
        session.add_all(
            [
                CandidateJobScore(
                    candidate_id="candidate_alpha",
                    job_id=job.id,
                    scoring_version=1,
                    total_score=Decimal("80"),
                    dimensions={},
                    rationale={},
                    meets_threshold=True,
                ),
                CandidateJobScore(
                    candidate_id="candidate_beta",
                    job_id=job.id,
                    scoring_version=1,
                    total_score=Decimal("50"),
                    dimensions={},
                    rationale={},
                    meets_threshold=False,
                ),
            ]
        )
        session.commit()

        alpha_scores = session.scalars(
            select(CandidateJobScore).where(CandidateJobScore.candidate_id == "candidate_alpha")
        ).all()

    assert len(alpha_scores) == 1
    assert alpha_scores[0].candidate_id == "candidate_alpha"
    assert alpha_scores[0].total_score == Decimal("80.00")


def test_application_children_cannot_cross_candidate_boundary() -> None:
    engine = _isolated_engine()
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        job = GlobalJob(
            source="fictional-board",
            external_id="tenant-job-1",
            company="Example Robotics Ltd",
            title="Backend Engineer",
            description="Fictional role",
            url="https://example.invalid/jobs/tenant-1",
        )
        session.add(job)
        session.flush()
        application = Application(
            candidate_id="candidate_alpha",
            job_id=job.id,
            state=ApplicationState.MATERIALS_READY,
        )
        session.add(application)
        session.flush()
        session.add(
            ApplicationDocument(
                candidate_id="candidate_beta",
                application_id=application.id,
                kind=DocumentKind.CV,
                version=1,
                storage_uri="artifact://candidate_beta/wrong-owner.pdf",
                sha256="a" * 64,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
