from __future__ import annotations

import hashlib
import json
from base64 import b64decode
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError

from app.auth.lifecycle import (
    CandidateDeletionError,
    CandidateDeletionRequest,
    CandidateLifecycleService,
)
from app.candidates.service import CandidateCreateRequest, CandidateNotFoundError, CandidateService
from app.db import build_session_factory
from app.domain.enums import ApplicationState, HumanActionKind
from app.domain.models import (
    AdministrativeAuditRecord,
    Application,
    ApplicationArtifact,
    ApplicationEvent,
    Base,
    BrowserSession,
    CandidateDeletionRecord,
    CandidateDiscoveryCommand,
    CandidateJobDecision,
    CandidateSettingsRecord,
    GlobalJob,
    HumanAction,
    WorkflowTask,
)
from app.tasks import TaskLeaseLostError, TaskQueue


def test_candidate_deletion_removes_owned_rows_and_files_but_retains_shared_data(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    candidates.create(
        CandidateCreateRequest(candidate_id="delete_me", display_name="Delete Me"),
        "create-delete-me",
    )
    candidates.create(
        CandidateCreateRequest(candidate_id="keep_me", display_name="Keep Me"),
        "create-keep-me",
    )
    with sessions.begin() as session:
        shared_job = GlobalJob(
            source="fictional-board",
            external_id="shared-delete-test",
            company="Fictional Systems",
            title="Fictional Engineer",
            description="A deterministic fictional role.",
            url="https://fictional.invalid/jobs/shared-delete-test",
        )
        session.add(shared_job)
        receipt_only_job = GlobalJob(
            source="fictional-board",
            external_id="receipt-only-delete-test",
            company="Fictional Receipt Systems",
            title="Receipt Engineer",
            description="A second deterministic fictional role.",
            url="https://fictional.invalid/jobs/receipt-only-delete-test",
        )
        session.add(receipt_only_job)
        session.flush()
        session.add_all(
            [
                CandidateSettingsRecord(candidate_id="delete_me", discovery_enabled=False),
                CandidateSettingsRecord(candidate_id="keep_me", discovery_enabled=False),
                CandidateJobDecision(
                    candidate_id="delete_me", job_id=shared_job.id, state="discovered"
                ),
                CandidateJobDecision(
                    candidate_id="keep_me", job_id=shared_job.id, state="discovered"
                ),
                WorkflowTask(
                    candidate_id="delete_me",
                    kind="candidate_readiness_check",
                    idempotency_key="delete-owned-task",
                ),
                AdministrativeAuditRecord(
                    candidate_id="delete_me",
                    actor_id="local-user",
                    event_type="candidate.test_event",
                    details={
                        "session_directory": "/tmp/private-session",
                        "nested": {
                            "screenshot_path": "/tmp/private-screenshot.png",
                            "safe": "portable",
                        },
                    },
                    event_hash="a" * 64,
                ),
                CandidateDiscoveryCommand(
                    candidate_id="delete_me",
                    idempotency_key="discovery-export-key",
                    request_sha256="b" * 64,
                    result={"job_ids": [str(receipt_only_job.id)]},
                ),
            ]
        )
    runtime_root = tmp_path / "runtime"
    for root in (
        runtime_root / "application_archive" / "delete_me",
        runtime_root / "candidates" / "delete_me",
    ):
        root.mkdir(parents=True)
        (root / "fictional.txt").write_text("fictional", encoding="utf-8")
    browser_root = runtime_root / "candidates" / "delete_me" / "sessions" / "session-one"
    browser_root.mkdir(parents=True)
    (browser_root / "final-page.json").write_text('{"safe": true}', encoding="utf-8")
    (browser_root / "playwright-final-page.png").write_bytes(b"fictional-png")
    (browser_root / "playwright-final-page.html").write_text(
        "<html>fictional final page</html>", encoding="utf-8"
    )
    (browser_root / "playwright-session.json").write_text(
        json.dumps(
            {
                "final_submit_clicked": False,
                "persistent_profile_directory": "/tmp/private-playwright-profile",
            }
        ),
        encoding="utf-8",
    )
    (browser_root / "cookies.json").write_text("secret-cookie", encoding="utf-8")
    service = CandidateLifecycleService(sessions, candidates, runtime_root)
    request = CandidateDeletionRequest(confirmation="delete_me", delete_archives=True)

    exported = service.export_candidate("delete_me", now=datetime(2026, 8, 5, 10, tzinfo=UTC))
    assert exported.schema_version == "1.0"
    assert any(item.path == "application_archive/fictional.txt" for item in exported.files)
    archive_entry = next(
        item for item in exported.files if item.path == "application_archive/fictional.txt"
    )
    assert b64decode(archive_entry.content_base64) == b"fictional"
    assert len(exported.database["global_jobs"]) == 2
    assert len(exported.database["candidate_job_decisions"]) == 1
    assert all(
        "idempotency_key" not in key
        for rows in exported.database.values()
        for row in rows
        for key in row
    )
    exported_audit = exported.database["administrative_audit_records"][0]
    assert exported_audit["details"] == {"nested": {"safe": "portable"}}
    assert any(item.path.endswith("final-page.json") for item in exported.files)
    assert any(item.path.endswith("playwright-final-page.png") for item in exported.files)
    assert any(item.path.endswith("playwright-final-page.html") for item in exported.files)
    playwright_metadata = next(
        item for item in exported.files if item.path.endswith("playwright-session.json")
    )
    assert (
        "persistent_profile_directory" not in b64decode(playwright_metadata.content_base64).decode()
    )
    assert all("cookies.json" not in item.path for item in exported.files)

    result = service.delete_candidate("delete_me", request, "delete-candidate-command")
    replay = service.delete_candidate("delete_me", request, "delete-candidate-command")

    assert result == replay
    assert result.status == "completed"
    assert set(result.deleted_paths) == {
        "application_archive",
        "candidate_runtime",
        "candidate_configuration",
    }
    assert not (copied_candidates_root / "delete_me").exists()
    assert not (runtime_root / "application_archive" / "delete_me").exists()
    assert not (runtime_root / "candidates" / "delete_me").exists()
    assert candidates.get_config("keep_me").manifest.candidate_id == "keep_me"
    with pytest.raises(CandidateNotFoundError, match="candidate not found"):
        candidates.create(
            CandidateCreateRequest(candidate_id="delete_me", display_name="Again"),
            "recreate-delete-me",
        )
    with sessions() as session:
        assert session.scalar(select(func.count(GlobalJob.id))) == 2
        assert (
            session.scalar(
                select(func.count(CandidateSettingsRecord.id)).where(
                    CandidateSettingsRecord.candidate_id == "delete_me"
                )
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count(CandidateSettingsRecord.id)).where(
                    CandidateSettingsRecord.candidate_id == "keep_me"
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count(WorkflowTask.id)).where(WorkflowTask.candidate_id == "delete_me")
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count(AdministrativeAuditRecord.id)).where(
                    AdministrativeAuditRecord.candidate_id == "delete_me"
                )
            )
            == 0
        )
        deletion_audits = session.scalars(select(AdministrativeAuditRecord)).all()
        assert [record.event_type for record in deletion_audits] == [
            "candidate.deletion_started",
            "candidate.deletion_completed",
        ]
        assert all(record.candidate_id.startswith("deleted_") for record in deletion_audits)
        tombstone = session.get(CandidateDeletionRecord, "delete_me")
        assert tombstone is not None and tombstone.status == "completed"


def test_candidate_deletion_is_payload_bound_and_protects_template(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    service = CandidateLifecycleService(sessions, candidates, tmp_path / "runtime")

    with pytest.raises(CandidateDeletionError) as protected:
        service.delete_candidate(
            "example_candidate",
            CandidateDeletionRequest(confirmation="example_candidate", delete_archives=True),
            "delete-protected-template",
        )
    assert protected.value.code == "protected_candidate"
    with pytest.raises(CandidateDeletionError) as confirmation:
        service.delete_candidate(
            "fictional_missing",
            CandidateDeletionRequest(confirmation="different", delete_archives=True),
            "delete-wrong-confirmation",
        )
    assert confirmation.value.code == "confirmation_mismatch"


def test_conflicting_deletion_key_does_not_hide_unreserved_candidate(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    candidates.create(
        CandidateCreateRequest(candidate_id="first_delete", display_name="First"),
        "create-first-delete",
    )
    candidates.create(
        CandidateCreateRequest(candidate_id="second_keep", display_name="Second"),
        "create-second-keep",
    )
    service = CandidateLifecycleService(sessions, candidates, tmp_path / "runtime")
    shared_key = "globally-bound-deletion-command"

    service.delete_candidate(
        "first_delete",
        CandidateDeletionRequest(confirmation="first_delete", delete_archives=True),
        shared_key,
    )
    with pytest.raises(CandidateDeletionError) as conflict:
        service.delete_candidate(
            "second_keep",
            CandidateDeletionRequest(confirmation="second_keep", delete_archives=True),
            shared_key,
        )

    assert conflict.value.code == "idempotency_conflict"
    assert not candidates.is_deletion_marked("second_keep")
    assert candidates.get_config("second_keep").manifest.candidate_id == "second_keep"
    with sessions() as session:
        assert session.get(CandidateDeletionRecord, "second_keep") is None


def test_marker_only_crash_state_is_status_visible_and_recoverable(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    candidates.create(
        CandidateCreateRequest(candidate_id="marker_recover", display_name="Marker"),
        "create-marker-recover",
    )
    request = CandidateDeletionRequest(confirmation="marker_recover", delete_archives=True)
    request_sha256 = hashlib.sha256(
        json.dumps(
            {"candidate_id": "marker_recover", **request.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    candidates.mark_for_deletion("marker_recover", request_sha256)
    lifecycle = CandidateLifecycleService(sessions, candidates, tmp_path / "runtime")

    status = lifecycle.deletion_status("marker_recover")
    assert lifecycle.is_deleted("marker_recover")
    assert status.status == "failed"
    assert status.error_code == "deletion_interrupted_before_receipt"
    result = lifecycle.delete_candidate("marker_recover", request, "recover-marker-command")
    assert result.status == "completed"


def test_unsafe_runtime_symlink_fails_closed_without_following_target(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    candidates.create(
        CandidateCreateRequest(candidate_id="unsafe_delete", display_name="Unsafe"),
        "create-unsafe-delete",
    )
    runtime_root = tmp_path / "runtime"
    target = runtime_root / "candidates" / "unsafe_delete"
    outside = tmp_path / "outside"
    target.mkdir(parents=True)
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    (target / "escape").symlink_to(outside, target_is_directory=True)
    service = CandidateLifecycleService(sessions, candidates, runtime_root)

    with pytest.raises(CandidateDeletionError) as error:
        service.delete_candidate(
            "unsafe_delete",
            CandidateDeletionRequest(confirmation="unsafe_delete", delete_archives=True),
            "delete-unsafe-candidate",
        )

    assert error.value.code == "unsafe_candidate_path"
    assert sentinel.read_text(encoding="utf-8") == "keep"
    with sessions() as session:
        record = session.get(CandidateDeletionRecord, "unsafe_delete")
        assert record is not None and record.status == "failed"


def test_migration_writer_fence_rejects_resurrection(tmp_path: Path, project_root: Path) -> None:
    database_path = tmp_path / "fenced.db"
    url = f"sqlite+pysqlite:///{database_path}"
    config = Config(project_root / "alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    sessions = build_session_factory(engine)
    queue = TaskQueue(sessions)
    leased = queue.enqueue(
        candidate_id="deleted_candidate",
        kind="candidate_readiness_check",
        idempotency_key="stale-before-deletion",
    )
    claimed = queue.claim(worker_id="stale-worker")
    assert claimed is not None and claimed.task_id == leased.task_id
    with sessions.begin() as session:
        session.add(
            CandidateDeletionRecord(
                candidate_id="deleted_candidate",
                idempotency_key_sha256="b" * 64,
                request_sha256="b" * 64,
                status="completed",
            )
        )
    with pytest.raises(IntegrityError, match="candidate is deleted"), sessions.begin() as session:
        session.add(CandidateSettingsRecord(candidate_id="deleted_candidate"))
    with pytest.raises(TaskLeaseLostError, match="lifecycle"):
        queue.enqueue(
            candidate_id="deleted_candidate",
            kind="candidate_readiness_check",
            idempotency_key="stale-after-deletion",
        )
    with pytest.raises(TaskLeaseLostError, match="lifecycle"):
        queue.complete(leased.task_id, worker_id="stale-worker")

    with engine.connect() as connection:
        trigger_names = set(
            connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            ).scalars()
        )
    excluded = {
        "candidate_deletion_records",
        "global_jobs",
        "job_versions",
    }
    for table in Base.metadata.sorted_tables:
        if "candidate_id" in table.c and table.name not in excluded:
            assert f"trg_{table.name}_candidate_not_deleted_insert" in trigger_names
            assert f"trg_{table.name}_candidate_not_deleted_update" in trigger_names
    with pytest.raises(IntegrityError, match="candidate is deleted"), sessions.begin() as session:
        session.add(
            AdministrativeAuditRecord(
                candidate_id="deleted_candidate",
                actor_id="stale-worker",
                event_type="stale.audit",
                event_hash="d" * 64,
            )
        )


def test_retention_sweep_removes_expired_ready_browser_files(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    now = datetime(2026, 8, 5, 12, tzinfo=UTC)
    with sessions.begin() as session:
        job = GlobalJob(
            source="fictional-board",
            external_id="retention-job",
            company="Fictional Systems",
            title="Retention Test",
            description="Fictional role.",
            url="https://fictional.invalid/jobs/retention",
        )
        session.add(job)
        session.flush()
        application = Application(
            candidate_id="example_candidate",
            job_id=job.id,
        )
        session.add(application)
        session.flush()
        browser_session = BrowserSession(
            candidate_id="example_candidate",
            application_id=application.id,
            status="ready",
            updated_at=now - timedelta(days=8),
        )
        session.add(browser_session)
        session.add(
            CandidateSettingsRecord(
                candidate_id="example_candidate", browser_session_retention_days=7
            )
        )
        session.flush()
        session_id = browser_session.id
    session_root = (
        tmp_path / "runtime" / "candidates" / "example_candidate" / "sessions" / str(session_id)
    )
    session_root.mkdir(parents=True)
    (session_root / "cookies.json").write_text("fictional", encoding="utf-8")
    service = CandidateLifecycleService(sessions, candidates, tmp_path / "runtime")

    assert service.purge_expired_browser_sessions("example_candidate", now=now) == 1
    assert service.purge_expired_browser_sessions("example_candidate", now=now) == 0
    assert not session_root.exists()
    with sessions() as session:
        stored = session.get(BrowserSession, session_id)
        assert stored is not None
        assert stored.status == "retained_metadata"
        assert stored.external_session_ref is None
        audit = session.scalar(
            select(AdministrativeAuditRecord).where(
                AdministrativeAuditRecord.candidate_id == "example_candidate",
                AdministrativeAuditRecord.event_type == "candidate.browser_retention_applied",
            )
        )
        assert audit is not None


def test_retention_sweep_removes_expired_human_takeover_profile(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    now = datetime(2026, 8, 5, 12, tzinfo=UTC)
    with sessions.begin() as session:
        job = GlobalJob(
            source="fictional-board",
            external_id="expired-human-retention",
            company="Fictional Systems",
            title="Expired Human Action",
            description="Fictional role.",
            url="https://fictional.invalid/jobs/expired-human-retention",
        )
        session.add(job)
        session.flush()
        application = Application(
            candidate_id="example_candidate",
            job_id=job.id,
            state=ApplicationState.HUMAN_ACTION_REQUIRED,
        )
        session.add(application)
        session.flush()
        browser_session = BrowserSession(
            candidate_id="example_candidate",
            application_id=application.id,
            status="human_takeover_opened",
            updated_at=now - timedelta(days=8),
        )
        session.add(browser_session)
        session.flush()
        action = HumanAction(
            candidate_id="example_candidate",
            application_id=application.id,
            actor_id="system",
            action=HumanActionKind.PAUSE,
            status="pending",
            browser_session_id=browser_session.id,
            screenshot_uri="/fictional/screenshot.png",
            expires_at=now - timedelta(days=7),
        )
        session.add_all(
            [
                action,
                CandidateSettingsRecord(
                    candidate_id="example_candidate", browser_session_retention_days=7
                ),
            ]
        )
        session.flush()
        session_id = browser_session.id
        action_id = action.id
    session_root = (
        tmp_path / "runtime" / "candidates" / "example_candidate" / "sessions" / str(session_id)
    )
    session_root.mkdir(parents=True)
    (session_root / "cookies.json").write_text("fictional", encoding="utf-8")
    service = CandidateLifecycleService(sessions, candidates, tmp_path / "runtime")

    assert service.purge_expired_browser_sessions("example_candidate", now=now) == 1
    assert not session_root.exists()
    with sessions() as session:
        stored_session = session.get(BrowserSession, session_id)
        stored_action = session.get(HumanAction, action_id)
        stored_application = session.get(Application, application.id)
        assert stored_session is not None and stored_session.status == "retained_metadata"
        assert stored_action is not None and stored_action.status == "cancelled"
        assert stored_action.screenshot_uri is None
        assert (
            stored_application is not None
            and stored_application.state is ApplicationState.FORM_FILLING
        )
        event = session.scalar(
            select(ApplicationEvent).where(
                ApplicationEvent.application_id == application.id,
                ApplicationEvent.event_type == "HUMAN_ACTION_EXPIRED",
            )
        )
        assert event is not None and event.to_state is ApplicationState.FORM_FILLING
        assert event.payload["browser_profile_deleted"] is True
        assert event.payload["session_metadata_retained"] is True


def test_retention_restores_quarantine_when_metadata_transaction_fails(
    copied_candidates_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    now = datetime(2026, 8, 5, 12, tzinfo=UTC)
    with sessions.begin() as session:
        job = GlobalJob(
            source="fictional",
            external_id="retention-rollback",
            company="Fictional",
            title="Retention Rollback",
            description="Fictional.",
            url="https://fictional.invalid/retention-rollback",
        )
        session.add(job)
        session.flush()
        application = Application(candidate_id="example_candidate", job_id=job.id)
        session.add(application)
        session.flush()
        browser_session = BrowserSession(
            candidate_id="example_candidate",
            application_id=application.id,
            status="ready",
            updated_at=now - timedelta(days=8),
        )
        session.add_all(
            [
                browser_session,
                CandidateSettingsRecord(
                    candidate_id="example_candidate", browser_session_retention_days=7
                ),
            ]
        )
        session.flush()
        session_id = browser_session.id
    session_root = (
        tmp_path / "runtime" / "candidates" / "example_candidate" / "sessions" / str(session_id)
    )
    session_root.mkdir(parents=True)
    (session_root / "cookies.json").write_text("fictional", encoding="utf-8")
    lifecycle = CandidateLifecycleService(sessions, candidates, tmp_path / "runtime")

    def fail_audit(_session: object, _candidate_id: str, _event_type: str) -> None:
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(lifecycle, "_append_audit", fail_audit)

    with pytest.raises(RuntimeError, match="simulated audit failure"):
        lifecycle.purge_expired_browser_sessions("example_candidate", now=now)

    assert session_root.is_dir()
    with sessions() as session:
        stored = session.get(BrowserSession, session_id)
        assert stored is not None and stored.status == "ready"


def test_deletion_waits_for_candidate_filesystem_publishers_and_removes_late_output(
    copied_candidates_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "lifecycle-race.db"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    candidates.create(
        CandidateCreateRequest(candidate_id="lease_delete", display_name="Lease"),
        "create-lease-delete",
    )
    runtime_root = tmp_path / "runtime"
    lifecycle = CandidateLifecycleService(sessions, candidates, runtime_root)
    entered_fence = Event()
    finished = Event()
    failures: list[BaseException] = []
    original_fence = candidates.lifecycle_fence

    @contextmanager
    def observed_fence(candidate_id: str) -> Iterator[None]:
        entered_fence.set()
        with original_fence(candidate_id):
            yield

    monkeypatch.setattr(candidates, "lifecycle_fence", observed_fence)

    def erase() -> None:
        try:
            lifecycle.delete_candidate(
                "lease_delete",
                CandidateDeletionRequest(confirmation="lease_delete", delete_archives=True),
                "lease-delete-command",
            )
        except BaseException as exc:  # pragma: no cover - asserted in the parent thread
            failures.append(exc)
        finally:
            finished.set()

    with candidates.lifecycle_write("lease_delete"):
        worker = Thread(target=erase)
        worker.start()
        assert entered_fence.wait(timeout=5)
        assert not finished.is_set()
        late_output = runtime_root / "candidates" / "lease_delete" / "late-output.txt"
        late_output.parent.mkdir(parents=True)
        late_output.write_text("fictional", encoding="utf-8")

    worker.join(timeout=5)
    assert not worker.is_alive()
    assert failures == []
    assert not late_output.exists()


def test_export_rejects_a_file_swapped_to_an_outside_symlink(
    copied_candidates_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    candidates.create(
        CandidateCreateRequest(candidate_id="swap_export", display_name="Swap"),
        "create-swap-export",
    )
    candidate_file = copied_candidates_root / "swap_export" / "swap.txt"
    candidate_file.write_text("candidate", encoding="utf-8")
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("OUTSIDE_SECRET", encoding="utf-8")
    lifecycle = CandidateLifecycleService(sessions, candidates, tmp_path / "runtime")
    original_read = lifecycle._read_export_file

    def swap_then_read(root: Path, relative: Path) -> bytes:
        if relative.name == "swap.txt":
            candidate_file.unlink()
            candidate_file.symlink_to(outside)
        return original_read(root, relative)

    monkeypatch.setattr(lifecycle, "_read_export_file", swap_then_read)

    with pytest.raises(CandidateDeletionError) as error:
        lifecycle.export_candidate("swap_export")

    assert error.value.code == "unsafe_candidate_path"
    assert outside.read_text(encoding="utf-8") == "OUTSIDE_SECRET"


def test_failed_deletion_resumes_with_a_fresh_key_and_preserves_counts(
    copied_candidates_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "resume-deletion.db"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    candidates.create(
        CandidateCreateRequest(candidate_id="resume_delete", display_name="Resume"),
        "create-resume-delete",
    )
    with sessions.begin() as session:
        session.add(CandidateSettingsRecord(candidate_id="resume_delete"))
    request = CandidateDeletionRequest(confirmation="resume_delete", delete_archives=True)
    first = CandidateLifecycleService(sessions, candidates, tmp_path / "runtime")

    def interrupted_files(_candidate_id: str) -> tuple[str, ...]:
        raise CandidateDeletionError("simulated_interruption", "Simulated interruption.")

    monkeypatch.setattr(first, "_delete_files", interrupted_files)
    with pytest.raises(CandidateDeletionError) as interrupted:
        first.delete_candidate("resume_delete", request, "first-deletion-command")
    assert interrupted.value.code == "simulated_interruption"

    resumed = CandidateLifecycleService(sessions, candidates, tmp_path / "runtime")
    result = resumed.delete_candidate("resume_delete", request, "fresh-recovery-command")

    assert result.status == "completed"
    assert result.deleted_rows["candidate_settings"] == 1


def test_concurrent_identical_deletions_serialize_to_the_same_receipt(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    database_path = tmp_path / "concurrent-deletion.db"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    candidates.create(
        CandidateCreateRequest(candidate_id="concurrent_delete", display_name="Concurrent"),
        "create-concurrent-delete",
    )
    lifecycle = CandidateLifecycleService(sessions, candidates, tmp_path / "runtime")
    request = CandidateDeletionRequest(confirmation="concurrent_delete", delete_archives=True)
    start = Event()
    results: list[object] = []

    def erase() -> None:
        start.wait(timeout=5)
        try:
            results.append(
                lifecycle.delete_candidate(
                    "concurrent_delete", request, "concurrent-delete-command"
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted in the parent thread
            results.append(exc)

    workers = [Thread(target=erase), Thread(target=erase)]
    for worker in workers:
        worker.start()
    start.set()
    for worker in workers:
        worker.join(timeout=5)

    assert all(not worker.is_alive() for worker in workers)
    assert len(results) == 2
    assert results[0] == results[1]


def test_storage_reference_outside_canonical_roots_blocks_erasure_preflight(
    copied_candidates_root: Path, tmp_path: Path
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    candidates.create(
        CandidateCreateRequest(candidate_id="unsafe_ref", display_name="Unsafe Ref"),
        "create-unsafe-ref",
    )
    outside = tmp_path / "outside-artifact.txt"
    outside.write_text("retain", encoding="utf-8")
    with sessions.begin() as session:
        job = GlobalJob(
            source="fictional",
            external_id="unsafe-ref",
            company="Fictional",
            title="Unsafe Reference",
            description="Fictional.",
            url="https://fictional.invalid/unsafe-ref",
        )
        session.add(job)
        session.flush()
        application = Application(candidate_id="unsafe_ref", job_id=job.id)
        session.add(application)
        session.flush()
        session.add(
            ApplicationArtifact(
                candidate_id="unsafe_ref",
                application_id=application.id,
                kind="unsafe_test",
                version=1,
                storage_uri=str(outside),
                sha256="c" * 64,
                content_type="text/plain",
            )
        )
    lifecycle = CandidateLifecycleService(sessions, candidates, tmp_path / "runtime")

    with pytest.raises(CandidateDeletionError) as error:
        lifecycle.delete_candidate(
            "unsafe_ref",
            CandidateDeletionRequest(confirmation="unsafe_ref", delete_archives=True),
            "unsafe-ref-deletion",
        )

    assert error.value.code == "unsafe_storage_reference"
    assert outside.read_text(encoding="utf-8") == "retain"
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count(Application.id)).where(Application.candidate_id == "unsafe_ref")
            )
            == 1
        )
