from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.api import create_app
from app.applications import ApplicationService
from app.candidates.service import CandidateService
from app.core.settings import Settings
from app.db import build_session_factory
from app.domain.models import Base
from app.health import HealthReport, ServiceStatus
from app.job_service import DiscoveryRequest, JobService


class _HealthyServices:
    def check(self) -> HealthReport:
        available = ServiceStatus(status="available")
        return HealthReport(status="ok", api=available, database=available, redis=available)


def _client(candidates_root: Path, runtime_root: Path) -> tuple[TestClient, str]:
    scoring_path = candidates_root / "example_candidate" / "scoring_rules.json"
    scoring = json.loads(scoring_path.read_text(encoding="utf-8"))
    scoring["application_threshold"] = 40
    scoring["human_review_threshold"] = 30
    scoring_path.write_text(json.dumps(scoring), encoding="utf-8")

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(candidates_root)
    jobs = JobService(sessions, candidates)
    applications = ApplicationService(sessions, candidates, runtime_root)
    job_id = jobs.discover(
        DiscoveryRequest(
            candidate_id="example_candidate",
            platform="greenhouse",
            company="Fictional Robotics Ltd",
            company_domain="fictional-robotics.invalid",
            payloads=(
                {
                    "id": 601,
                    "title": "Machine Learning Engineer",
                    "content": "A deterministic synthetic role.",
                    "location": {"name": "Exampleton"},
                    "absolute_url": "https://boards.greenhouse.io/fictional/jobs/601",
                },
            ),
        )
    ).job_ids[0]
    jobs.analyze("example_candidate", job_id, "analyze-api-601")
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://unused:6379/0",
        candidates_root=candidates_root,
        cors_origins=("http://localhost:3000",),
        runtime_root=runtime_root,
        auth_required=True,
        local_token_secret="fictional-api-test-secret-that-is-long-enough",
    )
    return (
        TestClient(
            create_app(
                settings=settings,
                candidate_service=candidates,
                job_service=jobs,
                application_service=applications,
                health_checker=_HealthyServices(),
            )
        ),
        str(job_id),
    )


def test_authenticated_api_enforces_candidate_scope_csrf_and_backend_confirmation(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    client, job_id = _client(copied_candidates_root, tmp_path / "runtime")
    with client:
        assert client.get("/api/jobs?candidate_id=example_candidate").status_code == 401
        login = client.post("/api/auth/local-session", json={"candidate_id": "example_candidate"})
        assert login.status_code == 200
        tokens = login.json()
        auth = {"Authorization": f"Bearer {tokens['session_token']}"}
        mutation = {
            **auth,
            "X-CSRF-Token": tokens["csrf_token"],
            "Idempotency-Key": "api-command-0001",
        }

        denied_scope = client.get("/api/jobs?candidate_id=candidate_beta", headers=auth)
        assert denied_scope.status_code == 403
        missing_csrf = client.post(
            f"/api/jobs/{job_id}/generate-materials?candidate_id=example_candidate",
            headers={**auth, "Idempotency-Key": "api-generate-0001"},
        )
        assert missing_csrf.status_code == 403

        generated = client.post(
            f"/api/jobs/{job_id}/generate-materials?candidate_id=example_candidate",
            headers={**mutation, "Idempotency-Key": "api-generate-0001"},
        )
        assert generated.status_code == 200, generated.text
        application_id = generated.json()["application_id"]
        assert generated.json()["state"] == "review_pending"

        for suffix, endpoint, body in (
            ("approve", "approve-materials", None),
            ("start", "start", None),
            ("dry-run", "dry-run", {"challenge": None}),
        ):
            response = client.post(
                f"/api/applications/{application_id}/{endpoint}?candidate_id=example_candidate",
                headers={**mutation, "Idempotency-Key": f"api-{suffix}-0001"},
                json=body,
            )
            assert response.status_code == 200, response.text
        authorization = client.post(
            f"/api/applications/{application_id}/authorize?candidate_id=example_candidate",
            headers={**mutation, "Idempotency-Key": "api-authorize-0001"},
        )
        assert authorization.status_code == 200, authorization.text
        outcome = client.post(
            f"/api/applications/{application_id}/submit?candidate_id=example_candidate",
            headers={**mutation, "Idempotency-Key": "api-submit-0001"},
            json={
                "authorization_id": authorization.json()["authorization_id"],
                "synthetic_fixture_acknowledged": True,
                "backend_confirmation_detected": False,
                "confirmation_reference": None,
            },
        )
        correspondence = client.post(
            "/api/correspondence/ingest",
            headers={**mutation, "Idempotency-Key": "api-correspondence-0001"},
            json={
                "candidate_id": "example_candidate",
                "provider_message_id": "api-recruiter-601",
                "sender": "recruiting@fictional-robotics.invalid",
                "recipients": ["morgan@example.invalid"],
                "subject": "Recruiter update for application 601",
                "body_text": "A recruiter would like to discuss your background.",
                "received_at": "2026-08-05T15:00:00Z",
            },
        )
        interview_package = client.post(
            f"/api/applications/{application_id}/prepare-interview?candidate_id=example_candidate",
            headers={**mutation, "Idempotency-Key": "api-interview-0001"},
        )
        notifications = client.get(
            "/api/notifications?candidate_id=example_candidate", headers=auth
        )

    assert outcome.status_code == 200, outcome.text
    assert outcome.json()["successful"] is False
    assert outcome.json()["state"] == "failed_retryable"
    assert outcome.json()["status"] == "confirmation_missing"
    assert correspondence.status_code == 200, correspondence.text
    assert correspondence.json()["application_id"] == application_id
    assert interview_package.status_code == 200, interview_package.text
    assert interview_package.json()["company"] == "Fictional Robotics Ltd"
    assert notifications.status_code == 200
    assert notifications.json()[0]["event_type"] == "correspondence_recruiter"
