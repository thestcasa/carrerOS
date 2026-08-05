# Operations

Start the local stack with `docker compose up --build`. The UI is at `http://localhost:3000`, the
API at `http://localhost:8000`, and API documentation at `/docs`. Services bind to `127.0.0.1`.
PostgreSQL, Redis, candidate data, and runtime artifacts use separate volumes.

Useful commands:

```bash
alembic upgrade head
alembic check
python -m app onboard --candidate fictional_friend --display-name "Fictional Friend" \
  --idempotency-key onboard-fictional-friend
python -m app validate-candidate --candidate fictional_friend
python -m app readiness --candidate fictional_friend
python -m app export-candidate --candidate fictional_friend
python -m app deletion-status --candidate fictional_friend
python -m app delete-candidate --candidate fictional_friend \
  --confirmation fictional_friend --idempotency-key operator-chosen-command-key
python -m app import-cv --candidate fictional_friend --file /private/path/cv.txt \
  --idempotency-key import-fictional-friend-cv
python -m app discover --candidate fictional_friend --fixture fixtures/jobs.json
python -m app.browser.fixture_server --port 8090
```

CV import retains only a structured unapproved draft and the raw document hash. The raw TXT is
not copied into candidate storage. Use `--apply` only after inspecting the extraction; applied facts
remain readiness blockers until explicitly approved in the versioned profile.

For a host-native synthetic browser test, install the pinned Python dependencies and Chromium:

```bash
python -m playwright install --with-deps chromium
pytest tests/test_playwright_browser.py
```

The fixture server rejects non-loopback binds. The browser harness requires an exact configured
fixture URL, validates uploads against the candidate runtime directory and expected hashes, permits
only its first GET document request, and never clicks the fixture's final-submit control. It is a
test harness, not the application's production browser transport.

New candidates are unapproved, blocked drafts with an `.invalid` address. Complete and approve
legal/profile/answer configuration before enabling discovery; autonomous mode has additional
tested-adapter, dry-run, and explicit-confirmation blockers. The emergency stop denies new
authorizations immediately.

Export reads a repeatable candidate snapshot, includes exact archives and safe browser evidence,
and excludes browser profiles, credentials, idempotency secrets, capability tokens, and local
storage paths. The API returns it with `no-store` and an attachment filename.

Deletion is irreversible. Back up and inspect the portable export first, type the exact candidate
ID, and keep the command key until a completed receipt is returned. The marker is installed inside
the durable tombstone transaction, and the service can recover either a marker-only crash state or
a failed receipt with the same payload. Use `deletion-status` to inspect recovery state; settings
exposes the same controls even when normal candidate reads are fenced. `example_candidate` is
deliberately protected.

The scheduler enqueues a daily retention sweep. `browser_session_retention_days` defaults to 30
and is configurable from 1 to 3650 in settings. Eligible confirmed/cancelled/ready sessions and
expired human-takeover profiles are quarantined, committed as retained metadata, then removed.
Expired human actions return their application to form filling with an audit event. Submitted
immutable archives are retained until intentional candidate deletion.

Back up candidate, PostgreSQL, and runtime volumes together. Application artifacts are immutable
and hash verified. A failed hash check is a security incident: stop automation, preserve the files,
and inspect event/security ledgers.

The autonomous development environment has no Docker binary, so Compose startup and configuration
parsing must be verified on a Docker-capable host. Its minimal musl runtime also cannot launch the
downloaded glibc Chromium
binary because required shared libraries are absent. The Dockerfile installs the supported browser
and dependencies; SQLite migrations and non-browser backend/frontend quality gates are the offline
verification path here.
