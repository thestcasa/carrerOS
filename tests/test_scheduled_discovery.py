from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select

from app.candidates.service import CandidateService
from app.db import build_session_factory
from app.discovery.providers import (
    FixtureProviderTransport,
    ProviderFeedClient,
    ProviderHttpResponse,
    provider_feed_url,
)
from app.discovery.scheduled import (
    DiscoverySourceCreate,
    DiscoverySourceUpdate,
    ScheduledDiscoveryError,
    ScheduledDiscoveryService,
)
from app.domain.models import (
    Base,
    CandidateDiscoveryCommand,
    CandidateDiscoveryRun,
    CandidateDiscoverySourceCommand,
    CandidateJobScore,
    CandidateSettingsRecord,
    GlobalJob,
    JobVersion,
)
from app.job_service import JobService
from app.runtime import run_scheduler_once, run_worker_once
from app.tasks import TaskQueue, TaskView


def test_scheduled_source_runs_once_per_bucket_and_scores_safe_jobs(
    copied_candidates_root: Path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    jobs = JobService(sessions, candidates)
    url = provider_feed_url("greenhouse", "fictional")
    payload = {
        "jobs": [
            {
                "id": 9001,
                "title": "Machine Learning Engineer",
                "content": "Build truthful deterministic machine learning systems.",
                "location": {"name": "Exampleton"},
                "absolute_url": "https://boards.greenhouse.io/fictional/jobs/9001",
            }
        ]
    }
    fetcher = ProviderFeedClient(
        FixtureProviderTransport(
            {
                url: ProviderHttpResponse(
                    status_code=200,
                    final_url=url,
                    headers={"content-type": "application/json"},
                    body=json.dumps(payload).encode(),
                )
            }
        )
    )
    discovery = ScheduledDiscoveryService(sessions, candidates, jobs, fetcher)
    now = datetime(2026, 8, 5, 10, tzinfo=UTC)
    discovery.create_source(
        "example_candidate",
        DiscoverySourceCreate(
            provider="greenhouse",
            company="Fictional Robotics Ltd",
            company_domain="fictional-robotics.invalid",
            board_token="fictional",
            cadence_minutes=60,
        ),
        "create-source-9001",
        now=now,
    )
    with sessions.begin() as session:
        session.add(
            CandidateSettingsRecord(
                candidate_id="example_candidate",
                discovery_enabled=True,
                allowed_ats_adapters=["greenhouse"],
            )
        )
    queue = TaskQueue(sessions)

    first = run_scheduler_once(queue, candidates, now=now, discovery=discovery)
    replay = run_scheduler_once(queue, candidates, now=now, discovery=discovery)
    assert len(first) == 2
    assert len(replay) == 1
    assert replay[0].task_id in {item.task_id for item in first}
    assert run_worker_once(queue, candidates, worker_id="worker-a", now=now, discovery=discovery)
    completed = run_worker_once(
        queue, candidates, worker_id="worker-a", now=now, discovery=discovery
    )
    assert completed is not None and completed.kind == "discover_source"
    assert completed.status == "completed"

    source = discovery.list_sources("example_candidate")[0]
    assert source.last_status == "completed"
    assert source.last_discovered == 1
    assert source.last_unchanged == 0
    next_hour = datetime(2026, 8, 5, 11, tzinfo=UTC)
    assert len(run_scheduler_once(queue, candidates, now=next_hour, discovery=discovery)) == 2
    assert run_worker_once(
        queue, candidates, worker_id="worker-a", now=next_hour, discovery=discovery
    )
    assert run_worker_once(
        queue, candidates, worker_id="worker-a", now=next_hour, discovery=discovery
    )
    latest = discovery.list_sources("example_candidate")[0]
    assert latest.last_discovered == 0
    assert latest.last_unchanged == 1
    with sessions() as session:
        assert session.scalar(select(func.count(JobVersion.id))) == 1
        assert session.scalar(select(func.count(CandidateJobScore.id))) == 1
        assert session.scalar(select(func.count(CandidateDiscoveryRun.id))) == 2


def test_disabled_source_is_not_scheduled(copied_candidates_root: Path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    discovery = ScheduledDiscoveryService(
        sessions,
        candidates,
        JobService(sessions, candidates),
        ProviderFeedClient(FixtureProviderTransport({})),
    )
    now = datetime(2026, 8, 5, 10, tzinfo=UTC)
    discovery.create_source(
        "example_candidate",
        DiscoverySourceCreate(
            provider="lever",
            company="Fictional Systems",
            company_domain="fictional.invalid",
            board_token="fictional",
            enabled=False,
        ),
        "create-source-disabled",
        now=now,
    )

    scheduled = discovery.enqueue_due(TaskQueue(sessions), now=now)

    assert not scheduled


def test_missing_settings_and_empty_adapter_allowlist_fail_closed(
    copied_candidates_root: Path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    discovery = ScheduledDiscoveryService(
        sessions,
        candidates,
        JobService(sessions, candidates),
        ProviderFeedClient(FixtureProviderTransport({})),
    )
    now = datetime(2026, 8, 5, 10, tzinfo=UTC)
    discovery.create_source(
        "example_candidate",
        DiscoverySourceCreate(
            provider="lever",
            company="Fictional Systems",
            company_domain="fictional.invalid",
            board_token="fictional",
        ),
        "source-no-policy",
        now=now,
    )
    queue = TaskQueue(sessions)

    assert not discovery.enqueue_due(queue, now=now)
    with sessions.begin() as session:
        session.add(
            CandidateSettingsRecord(
                candidate_id="example_candidate",
                discovery_enabled=True,
                allowed_ats_adapters=[],
            )
        )
    assert not discovery.enqueue_due(queue, now=now)


def test_policy_change_after_enqueue_prevents_provider_fetch(
    copied_candidates_root: Path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    transport = FixtureProviderTransport({})
    discovery = ScheduledDiscoveryService(
        sessions,
        candidates,
        JobService(sessions, candidates),
        ProviderFeedClient(transport),
    )
    now = datetime(2026, 8, 5, 10, tzinfo=UTC)
    discovery.create_source(
        "example_candidate",
        DiscoverySourceCreate(
            provider="lever",
            company="Fictional Systems",
            company_domain="fictional.invalid",
            board_token="fictional",
        ),
        "create-source-policy",
        now=now,
    )
    queue = TaskQueue(sessions)
    with sessions.begin() as session:
        session.add(
            CandidateSettingsRecord(
                candidate_id="example_candidate",
                discovery_enabled=True,
                allowed_ats_adapters=["lever"],
            )
        )
    assert len(discovery.enqueue_due(queue, now=now)) == 1
    with sessions.begin() as session:
        settings = session.scalar(select(CandidateSettingsRecord))
        assert settings is not None
        settings.discovery_enabled = False
        settings.allowed_ats_adapters = []

    completed = run_worker_once(
        queue, candidates, worker_id="worker-policy", now=now, discovery=discovery
    )

    assert completed is not None and completed.status == "completed"
    assert not transport.requests


def test_source_creation_idempotency_is_durable_and_payload_bound(
    copied_candidates_root: Path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    discovery = ScheduledDiscoveryService(
        sessions,
        candidates,
        JobService(sessions, candidates),
        ProviderFeedClient(FixtureProviderTransport({})),
    )
    command = DiscoverySourceCreate(
        provider="ashby",
        company="Fictional Labs",
        company_domain="fictional.invalid",
        board_token="fictional",
    )
    first = discovery.create_source("example_candidate", command, "source-command-1")
    assert (
        discovery.create_source("example_candidate", command, "source-command-1").source_id
        == first.source_id
    )
    with pytest.raises(ScheduledDiscoveryError, match="reused"):
        discovery.create_source(
            "example_candidate",
            command.model_copy(update={"cadence_minutes": 120}),
            "source-command-1",
        )


def test_source_update_idempotency_is_durable_and_payload_bound(
    copied_candidates_root: Path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    discovery = ScheduledDiscoveryService(
        sessions,
        candidates,
        JobService(sessions, candidates),
        ProviderFeedClient(FixtureProviderTransport({})),
    )
    source = discovery.create_source(
        "example_candidate",
        DiscoverySourceCreate(
            provider="ashby",
            company="Fictional Labs",
            company_domain="fictional.invalid",
            board_token="fictional",
        ),
        "source-update-create",
    )
    update = DiscoverySourceUpdate(enabled=False, cadence_minutes=120)

    first = discovery.update_source(
        "example_candidate", source.source_id, update, "source-update-command"
    )
    replay = discovery.update_source(
        "example_candidate", source.source_id, update, "source-update-command"
    )

    assert first == replay
    assert not replay.enabled and replay.cadence_minutes == 120
    with sessions() as session:
        assert session.scalar(select(func.count(CandidateDiscoverySourceCommand.id))) == 1
    with pytest.raises(ScheduledDiscoveryError, match="reused"):
        discovery.update_source(
            "example_candidate",
            source.source_id,
            DiscoverySourceUpdate(enabled=True),
            "source-update-command",
        )


def test_stale_discovery_lease_cannot_reacquire_or_overwrite_run(
    copied_candidates_root: Path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    transport = FixtureProviderTransport({})
    discovery = ScheduledDiscoveryService(
        sessions,
        candidates,
        JobService(sessions, candidates),
        ProviderFeedClient(transport),
    )
    source = discovery.create_source(
        "example_candidate",
        DiscoverySourceCreate(
            provider="greenhouse",
            company="Fictional Labs",
            company_domain="fictional.invalid",
            board_token="fictional",
        ),
        "source-stale-lease",
    )
    with sessions.begin() as session:
        session.add(
            CandidateSettingsRecord(
                candidate_id="example_candidate",
                discovery_enabled=True,
                allowed_ats_adapters=["greenhouse"],
            )
        )
        session.add(
            CandidateDiscoveryRun(
                candidate_id="example_candidate",
                source_id=source.source_id,
                cadence_bucket="bucket-1",
                status="running",
                lease_attempt=2,
            )
        )
    stale = TaskView(
        task_id=uuid4(),
        candidate_id="example_candidate",
        kind="discover_source",
        status="running",
        payload={"source_id": str(source.source_id), "cadence_bucket": "bucket-1"},
        attempts=1,
        max_attempts=3,
        scheduled_for=datetime(2026, 8, 5, 10, tzinfo=UTC),
        locked_by="worker-stale",
        last_error=None,
    )

    with pytest.raises(ScheduledDiscoveryError, match="superseded"):
        discovery.execute_task(stale)
    assert not transport.requests
    with sessions() as session:
        run = session.scalar(select(CandidateDiscoveryRun))
        assert run is not None and run.lease_attempt == 2 and run.status == "running"


def test_lease_superseded_during_fetch_blocks_discovery_side_effects(
    copied_candidates_root: Path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    candidates = CandidateService(copied_candidates_root)
    source_id = None

    class SupersedingFetcher:
        def fetch(self, provider: str, board_token: str) -> tuple[dict[str, object], ...]:
            assert provider == "greenhouse" and board_token == "fictional"
            with sessions.begin() as session:
                run = session.scalar(select(CandidateDiscoveryRun))
                assert run is not None
                run.lease_attempt = 2
            return (
                {
                    "id": 9100,
                    "title": "Fictional Engineer",
                    "content": "Build safe systems.",
                    "location": {"name": "Exampleton"},
                    "absolute_url": "https://boards.greenhouse.io/fictional/jobs/9100",
                },
            )

    discovery = ScheduledDiscoveryService(
        sessions,
        candidates,
        JobService(sessions, candidates),
        SupersedingFetcher(),
    )
    source = discovery.create_source(
        "example_candidate",
        DiscoverySourceCreate(
            provider="greenhouse",
            company="Fictional Labs",
            company_domain="fictional.invalid",
            board_token="fictional",
        ),
        "source-side-effect-fence",
    )
    source_id = source.source_id
    with sessions.begin() as session:
        session.add(
            CandidateSettingsRecord(
                candidate_id="example_candidate",
                discovery_enabled=True,
                allowed_ats_adapters=["greenhouse"],
            )
        )
    task = TaskView(
        task_id=uuid4(),
        candidate_id="example_candidate",
        kind="discover_source",
        status="running",
        payload={"source_id": str(source_id), "cadence_bucket": "bucket-side-effect"},
        attempts=1,
        max_attempts=3,
        scheduled_for=datetime(2026, 8, 5, 10, tzinfo=UTC),
        locked_by="worker-stale",
        last_error=None,
    )

    with pytest.raises(ScheduledDiscoveryError, match="superseded"):
        discovery.execute_task(task)
    with sessions() as session:
        assert session.scalar(select(func.count(GlobalJob.id))) == 0
        assert session.scalar(select(func.count(CandidateDiscoveryCommand.id))) == 0
