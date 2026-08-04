from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app
from app.candidates.service import CandidateService
from app.core.settings import Settings
from app.health import HealthReport, ServiceStatus


class _HealthyServices:
    def check(self) -> HealthReport:
        available = ServiceStatus(status="available")
        return HealthReport(status="ok", api=available, database=available, redis=available)


def _client(candidates_root: Path) -> TestClient:
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://unused:6379/0",
        candidates_root=candidates_root,
        cors_origins=("http://localhost:3000",),
    )
    return TestClient(
        create_app(
            settings=settings,
            candidate_service=CandidateService(candidates_root),
            health_checker=_HealthyServices(),
        )
    )


def test_candidate_list_and_health_are_available(copied_candidates_root: Path) -> None:
    with _client(copied_candidates_root) as client:
        health = client.get("/api/health")
        candidates = client.get("/api/candidates")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert candidates.status_code == 200
    assert candidates.json() == [
        {
            "candidate_id": "example_candidate",
            "display_name": "Morgan Example",
            "profile_version": "1.0.0",
            "configuration_status": "valid",
            "readiness_status": "ready",
            "automation_status": "disabled",
        }
    ]


def test_readiness_reports_domains_and_disabled_autonomy(
    copied_candidates_root: Path,
) -> None:
    with _client(copied_candidates_root) as client:
        response = client.get("/api/candidates/example_candidate/readiness")

    assert response.status_code == 200
    report = response.json()
    assert report["status"] == "ready"
    assert all(domain["status"] == "READY" for domain in report["domains"])
    autonomous = next(
        item for item in report["capabilities"] if item["capability"] == "autonomous_submission"
    )
    assert autonomous["status"] == "BLOCKED"
    assert autonomous["blockers"] == ["automatic_submission_disabled"]


def test_profile_update_is_validated_versioned_and_archived(
    copied_candidates_root: Path,
) -> None:
    candidate_dir = copied_candidates_root / "example_candidate"
    identity = json.loads((candidate_dir / "identity.json").read_text(encoding="utf-8"))
    identity["full_name"] = "Taylor Example"

    with _client(copied_candidates_root) as client:
        response = client.patch(
            "/api/candidates/example_candidate",
            json={"section": "identity", "data": identity},
        )
        detail = client.get("/api/candidates/example_candidate")

    assert response.status_code == 200
    assert response.json()["previous_version"] == "1.0.0"
    assert response.json()["profile_version"] == "1.0.1"
    assert detail.json()["config"]["identity"]["full_name"] == "Taylor Example"
    history = candidate_dir / ".history" / "1.0.0"
    assert (history / "profile.yaml").is_file()
    archived_identity = json.loads((history / "identity.json").read_text(encoding="utf-8"))
    assert archived_identity["full_name"] == "Morgan Example"


def test_invalid_update_fails_without_changing_version(copied_candidates_root: Path) -> None:
    candidate_dir = copied_candidates_root / "example_candidate"
    identity = json.loads((candidate_dir / "identity.json").read_text(encoding="utf-8"))
    identity["email"] = "not-an-email"

    with _client(copied_candidates_root) as client:
        response = client.patch(
            "/api/candidates/example_candidate",
            json={"section": "identity", "data": identity},
        )
        detail = client.get("/api/candidates/example_candidate")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "candidate_update_invalid"
    assert detail.json()["profile_version"] == "1.0.0"
    assert not (candidate_dir / ".history").exists()


def test_missing_candidate_returns_stable_error(copied_candidates_root: Path) -> None:
    with _client(copied_candidates_root) as client:
        response = client.get("/api/candidates/missing_candidate")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "candidate_not_found"
