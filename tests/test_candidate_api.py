from __future__ import annotations

import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app
from app.candidates.service import CandidateService
from app.core.settings import Settings
from app.db import build_engine
from app.domain.models import Base
from app.health import HealthReport, ServiceStatus


class _HealthyServices:
    def check(self) -> HealthReport:
        available = ServiceStatus(status="available")
        return HealthReport(status="ok", api=available, database=available, redis=available)


def _client(candidates_root: Path, *, auth_required: bool = False) -> TestClient:
    database_url = f"sqlite+pysqlite:///{candidates_root.parent / 'candidate-api.db'}"
    Base.metadata.create_all(build_engine(database_url))
    settings = Settings(
        database_url=database_url,
        redis_url="redis://unused:6379/0",
        candidates_root=candidates_root,
        cors_origins=("http://localhost:3000",),
        auth_required=auth_required,
        local_token_secret="fictional-local-token-secret-at-least-32-bytes",
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


def test_authenticated_onboarding_refreshes_candidate_ownership(
    copied_candidates_root: Path,
) -> None:
    with _client(copied_candidates_root, auth_required=True) as client:
        login = client.post("/api/auth/local-session", json={})
        tokens = login.json()
        headers = {
            "Authorization": f"Bearer {tokens['session_token']}",
            "X-CSRF-Token": tokens["csrf_token"],
        }
        created = client.post(
            "/api/candidates",
            headers=headers,
            json={"candidate_id": "fictional_friend", "display_name": "Fictional Friend"},
        )
        assert created.status_code == 200, created.text
        assert created.json()["readiness"]["status"] == "not_ready"
        assert (
            client.get(
                "/api/candidates/fictional_friend",
                headers={"Authorization": f"Bearer {tokens['session_token']}"},
            ).status_code
            == 403
        )
        refreshed = client.post("/api/auth/local-session", json={}).json()
        detail = client.get(
            "/api/candidates/fictional_friend",
            headers={"Authorization": f"Bearer {refreshed['session_token']}"},
        )
        assert detail.status_code == 200
        assert detail.json()["config"]["identity"]["email"].endswith(".invalid")


def test_cv_import_api_returns_unapproved_draft_then_applies_it(
    copied_candidates_root: Path,
) -> None:
    cv_text = """EDUCATION
Example Institute | BSc | Data Science | Exampleton | 2018-09 | 2021-06
EXPERIENCE
Fictional Systems Inc | Data Engineer | Remote | 2021-07 | 2023-12 | Python
- Built a fictional data quality check.
"""
    with _client(copied_candidates_root) as client:
        imported = client.post(
            "/api/candidates/example_candidate/cv-imports",
            json={
                "filename": "fictional.txt",
                "content_base64": base64.b64encode(cv_text.encode()).decode(),
            },
        )
        assert imported.status_code == 200, imported.text
        draft = imported.json()
        assert draft["approval_required"] is True
        assert draft["experience"]["items"][0]["approved"] is False

        applied = client.post(
            f"/api/candidates/example_candidate/cv-imports/{draft['import_id']}/apply"
        )

    assert applied.status_code == 200, applied.text
    assert applied.json()["profile_version"] == "1.0.1"
    assert applied.json()["readiness"]["status"] == "not_ready"


def test_cv_import_api_rejects_oversize_transport_before_json_buffering(
    copied_candidates_root: Path,
) -> None:
    with _client(copied_candidates_root) as client:
        response = client.post(
            "/api/candidates/example_candidate/cv-imports",
            headers={"Content-Length": "4000000"},
            content=b"{}",
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "cv_import_too_large"


def test_authenticated_cv_import_stream_cap_precedes_authorization_body_buffering(
    copied_candidates_root: Path,
) -> None:
    with _client(copied_candidates_root, auth_required=True) as client:
        tokens = client.post("/api/auth/local-session", json={}).json()
        response = client.post(
            "/api/candidates/example_candidate/cv-imports",
            headers={
                "Authorization": f"Bearer {tokens['session_token']}",
                "X-CSRF-Token": tokens["csrf_token"],
                "Content-Length": "1",
            },
            content=b"x" * 3_010_001,
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "cv_import_too_large"
