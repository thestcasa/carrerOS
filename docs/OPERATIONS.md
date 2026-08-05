# Operations

Start the local stack with `docker compose up --build`. The UI is at `http://localhost:3000`, the
API at `http://localhost:8000`, and API documentation at `/docs`. Services bind to `127.0.0.1`.
PostgreSQL, Redis, candidate data, and runtime artifacts use separate volumes.

Useful commands:

```bash
alembic upgrade head
alembic check
python -m app onboard --candidate fictional_friend --display-name "Fictional Friend"
python -m app validate-candidate --candidate fictional_friend
python -m app readiness --candidate fictional_friend
python -m app export-candidate --candidate fictional_friend
python -m app discover --candidate fictional_friend --fixture fixtures/jobs.json
python -m app.browser.fixture_server --port 8090
```

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

Back up candidate, PostgreSQL, and runtime volumes together. Application artifacts are immutable
and hash verified. A failed hash check is a security incident: stop automation, preserve the files,
and inspect event/security ledgers.

The autonomous development environment has no Docker binary, so Compose startup must be verified
on a Docker-capable host. Its minimal musl runtime also cannot launch the downloaded glibc Chromium
binary because required shared libraries are absent. The Dockerfile installs the supported browser
and dependencies; SQLite migrations and non-browser backend/frontend quality gates are the offline
verification path here.
