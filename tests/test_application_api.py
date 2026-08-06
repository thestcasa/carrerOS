from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.api import create_app
from app.applications import ApplicationService
from app.auth.lifecycle import CandidateLifecycleService
from app.candidates.service import CandidateService
from app.core.settings import Settings
from app.db import build_session_factory
from app.discovery.providers import FixtureProviderTransport, ProviderFeedClient
from app.discovery.scheduled import ScheduledDiscoveryService
from app.discovery.verification import StoredFixtureJobSourceVerifier
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
    source_verifier = StoredFixtureJobSourceVerifier()
    jobs = JobService(sessions, candidates, source_verifier)
    scheduled_discovery = ScheduledDiscoveryService(
        sessions,
        candidates,
        jobs,
        ProviderFeedClient(FixtureProviderTransport({})),
    )
    applications = ApplicationService(
        sessions,
        candidates,
        runtime_root,
        synthetic_confirmation=lambda _candidate_id, _application_id: None,
        source_verifier=source_verifier,
    )
    lifecycle = CandidateLifecycleService(sessions, candidates, runtime_root)
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
                scheduled_discovery_service=scheduled_discovery,
                candidate_lifecycle_service=lifecycle,
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
        assert (
            client.get("/api/jobs/sources?candidate_id=example_candidate", headers=auth).json()
            == []
        )
        source = client.post(
            "/api/jobs/sources?candidate_id=example_candidate",
            headers={**mutation, "Idempotency-Key": "api-source-0001"},
            json={
                "provider": "greenhouse",
                "company": "Fictional Robotics Ltd",
                "company_domain": "fictional-robotics.invalid",
                "board_token": "fictional",
                "cadence_minutes": 60,
                "enabled": True,
            },
        )
        assert source.status_code == 200
        assert source.json()["provider"] == "greenhouse"
        source_id = source.json()["source_id"]
        missing_update_key = client.patch(
            f"/api/jobs/sources/{source_id}?candidate_id=example_candidate",
            headers={"Authorization": auth["Authorization"], "X-CSRF-Token": tokens["csrf_token"]},
            json={"enabled": False},
        )
        assert missing_update_key.status_code == 422
        updated_source = client.patch(
            f"/api/jobs/sources/{source_id}?candidate_id=example_candidate",
            headers={**mutation, "Idempotency-Key": "api-source-update-0001"},
            json={"enabled": False},
        )
        assert updated_source.status_code == 200
        assert updated_source.json()["enabled"] is False

        missing_settings_key = client.patch(
            "/api/settings",
            headers={"Authorization": auth["Authorization"], "X-CSRF-Token": tokens["csrf_token"]},
            json={"candidate_id": "example_candidate", "discovery_enabled": False},
        )
        assert missing_settings_key.status_code == 422
        settings_headers = {**mutation, "Idempotency-Key": "api-settings-0001"}
        settings_update = {"candidate_id": "example_candidate", "discovery_enabled": False}
        first_settings = client.patch(
            "/api/settings", headers=settings_headers, json=settings_update
        )
        replayed_settings = client.patch(
            "/api/settings", headers=settings_headers, json=settings_update
        )
        conflicting_settings = client.patch(
            "/api/settings",
            headers=settings_headers,
            json={"candidate_id": "example_candidate", "discovery_enabled": True},
        )
        assert first_settings.status_code == 200
        assert replayed_settings.json() == first_settings.json()
        assert conflicting_settings.status_code == 409

        generated = client.post(
            f"/api/jobs/{job_id}/generate-materials?candidate_id=example_candidate",
            headers={**mutation, "Idempotency-Key": "api-generate-0001"},
        )
        assert generated.status_code == 200, generated.text
        application_id = generated.json()["application_id"]
        assert generated.json()["state"] == "review_pending"
        draft_artifacts = client.get(
            f"/api/applications/{application_id}/artifacts?candidate_id=example_candidate",
            headers=auth,
        )
        assert draft_artifacts.status_code == 200
        rendered_cv = next(item for item in draft_artifacts.json() if item["kind"] == "rendered_cv")
        rendered_download = client.get(
            f"/api/applications/{application_id}/artifacts/{rendered_cv['artifact_id']}"
            "?candidate_id=example_candidate",
            headers=auth,
        )
        assert rendered_download.status_code == 200
        assert rendered_download.content.startswith(b"%PDF-1.4")
        assert hashlib.sha256(rendered_download.content).hexdigest() == rendered_cv["sha256"]
        assert rendered_cv["metadata"]["extraction_matches"] is True

        cv_document = next(item for item in generated.json()["documents"] if item["kind"] == "cv")
        revised_content = "\n\n".join(cv_document["content"].split("\n\n")[:-1])
        revision_body = {
            "document_id": cv_document["document_id"],
            "base_version": cv_document["version"],
            "content": revised_content,
            "reason": "Keep the fictional CV concise.",
        }
        revision_headers = {**mutation, "Idempotency-Key": "api-revision-0001"}
        revised = client.post(
            f"/api/applications/{application_id}/materials/revisions"
            "?candidate_id=example_candidate",
            headers=revision_headers,
            json=revision_body,
        )
        replayed_revision = client.post(
            f"/api/applications/{application_id}/materials/revisions"
            "?candidate_id=example_candidate",
            headers=revision_headers,
            json=revision_body,
        )
        conflicting_revision = client.post(
            f"/api/applications/{application_id}/materials/revisions"
            "?candidate_id=example_candidate",
            headers=revision_headers,
            json={**revision_body, "content": cv_document["content"]},
        )
        forged_actor = client.post(
            f"/api/applications/{application_id}/materials/revisions"
            "?candidate_id=example_candidate",
            headers={**mutation, "Idempotency-Key": "api-revision-forged-0001"},
            json={**revision_body, "actor_id": "forged-user"},
        )
        assert revised.status_code == 200, revised.text
        assert replayed_revision.json() == revised.json()
        assert conflicting_revision.status_code == 409
        assert forged_actor.status_code == 422
        cv_versions = [item for item in revised.json()["documents"] if item["kind"] == "cv"]
        assert [item["version"] for item in cv_versions] == [1, 2]
        assert cv_versions[0]["immutable"] is True
        assert cv_versions[1]["revision_actor"] == "local-user"

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


def test_candidate_deletion_requires_confirmation_and_revokes_stale_grant(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    client, _job_id = _client(copied_candidates_root, tmp_path / "runtime-delete")
    with client:
        initial = client.post(
            "/api/auth/local-session", json={"candidate_id": "example_candidate"}
        ).json()
        initial_headers = {
            "Authorization": f"Bearer {initial['session_token']}",
            "X-CSRF-Token": initial["csrf_token"],
        }
        created = client.post(
            "/api/candidates",
            headers={**initial_headers, "Idempotency-Key": "create-delete-api"},
            json={"candidate_id": "delete_api", "display_name": "Delete API"},
        )
        assert created.status_code == 200, created.text
        login = client.post("/api/auth/local-session", json={"candidate_id": "delete_api"}).json()
        headers = {
            "Authorization": f"Bearer {login['session_token']}",
            "X-CSRF-Token": login["csrf_token"],
            "Idempotency-Key": "delete-api-command",
        }
        portable_export = client.get(
            "/api/candidates/delete_api/export",
            headers={"Authorization": f"Bearer {login['session_token']}"},
        )
        assert portable_export.status_code == 200
        assert portable_export.json()["schema_version"] == "1.0"
        assert portable_export.json()["candidate_id"] == "delete_api"
        mismatch = client.request(
            "DELETE",
            "/api/candidates/delete_api",
            headers=headers,
            json={"confirmation": "wrong", "delete_archives": True},
        )
        assert mismatch.status_code == 422
        deleted = client.request(
            "DELETE",
            "/api/candidates/delete_api",
            headers=headers,
            json={"confirmation": "delete_api", "delete_archives": True},
        )
        replay = client.request(
            "DELETE",
            "/api/candidates/delete_api",
            headers=headers,
            json={"confirmation": "delete_api", "delete_archives": True},
        )
        stale_read = client.get(
            "/api/candidates/delete_api",
            headers={"Authorization": f"Bearer {login['session_token']}"},
        )
        recovery_login = client.post("/api/auth/local-session", json={}).json()
        recovery_headers = {
            "Authorization": f"Bearer {recovery_login['session_token']}",
            "X-CSRF-Token": recovery_login["csrf_token"],
            "Idempotency-Key": "delete-api-recovery-command",
        }
        recovery_status = client.get(
            "/api/candidates/delete_api/deletion",
            headers={"Authorization": recovery_headers["Authorization"]},
        )
        recovered = client.request(
            "DELETE",
            "/api/candidates/delete_api",
            headers=recovery_headers,
            json={"confirmation": "delete_api", "delete_archives": True},
        )

    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["status"] == "completed"
    assert replay.json() == deleted.json()
    assert stale_read.status_code == 410
    assert stale_read.json()["error"]["code"] == "candidate_deleted"
    assert recovery_status.status_code == 200
    assert recovery_status.json()["status"] == "completed"
    assert recovered.status_code == 200
    assert recovered.json() == deleted.json()
