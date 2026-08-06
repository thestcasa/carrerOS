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
python -m app export-configuration --candidate fictional_friend --format yaml \
  --file /private/path/fictional_friend.yaml
python -m app import-configuration --candidate fictional_friend \
  --file /private/path/fictional_friend.yaml --expected-profile-version 0.1.0 \
  --idempotency-key keep-this-key-until-success
python -m app deletion-status --candidate fictional_friend
python -m app delete-candidate --candidate fictional_friend \
  --confirmation fictional_friend --idempotency-key operator-chosen-command-key
python -m app import-cv --candidate fictional_friend --file /private/path/cv.txt \
  --idempotency-key import-fictional-friend-cv
python -m app discover --candidate fictional_friend --fixture fixtures/jobs.json
python -m app.browser.fixture_server --port 8090
python -m app run-browser-worker
```

CV import retains only a structured unapproved draft and the raw document hash. The raw TXT is
not copied into candidate storage. Use `--apply` only after inspecting the extraction; applied facts
remain readiness blockers until explicitly approved in the versioned profile.

For a host-native synthetic browser test, install the pinned Python dependencies and Chromium:

```bash
python -m playwright install --with-deps chromium
pytest tests/test_playwright_browser.py
```

The frontend has a separate deterministic route, safety, and accessibility suite. It intercepts
the API at the browser boundary and uses only fictional `.invalid` fixtures:

```bash
cd frontend
npm ci
npx playwright install --with-deps chromium
npm run test:e2e
```

Use `npx playwright test --list` to validate suite discovery without launching a browser. Browser
results and traces are written below `/tmp/carreros-playwright-results`, not into the repository.

The fixture server rejects non-loopback binds. The browser worker starts its own loopback fixture,
claims only `browser_dry_run` tasks, requires an exact configured URL, validates uploads against the
candidate runtime directory and expected hashes, permits only its first GET document request, and
never clicks the fixture's final-submit control. The normal worker cannot claim browser tasks.

Each attempt writes immutable `pre-submit.png`, `final-page.html`, and `manifest.json` evidence.
The manifest records the exact session, task attempt, profile reuse, URL, field keys, upload hashes,
network counts, and `submit_clicked=false`. Retryable timeouts, transient network failures, browser
crashes, and selector failures are bounded by the task's maximum attempts. Validation failures,
human verification, closed jobs, terminal rejection, and exhausted retries create a human action
and notification instead of silently looping. The application page polls durable state while a
worker owns or retries the task.

New candidates are unapproved, blocked drafts with an `.invalid` address. Complete and approve
legal/profile/answer configuration before enabling discovery; autonomous mode has additional
tested-adapter, dry-run, and explicit-confirmation blockers. The emergency stop denies new
authorizations immediately.

Export reads a repeatable candidate snapshot, includes exact archives and safe browser evidence,
and excludes browser profiles, credentials, idempotency secrets, capability tokens, and local
storage paths. The API returns it with `no-store` and an attachment filename.

Configuration export/import is a separate source-configuration transfer path. JSON and YAML files
are capped at 1 MiB and must retain their envelope hash and candidate identity. Import validates the
entire bundle and expected destination profile version before publishing one new version; a no-op
does not create history. Keep the same command key while retrying an uncertain response. Local
active/automation switches are preserved, and this operation never restores database workflow,
archives, profiles, secrets, or deletion state.

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

Back up candidate, PostgreSQL, and runtime volumes together. Application artifacts and browser
attempt evidence are immutable and hash verified. A failed hash check is a security incident: stop
automation, preserve the files, and inspect event/security ledgers. Synthetic confirmation does
not fabricate a screenshot; its receipt explicitly reports that no confirmation screenshot is
available.

The autonomous development environment has no Docker binary, so Compose startup and configuration
parsing must be verified on a Docker-capable host. Its minimal musl runtime downloads Chromium but
cannot launch the glibc binary because `libnspr4.so` and other required system libraries are
absent. The Dockerfile installs the supported browser
and dependencies; SQLite migrations and non-browser backend/frontend quality gates are the offline
verification path here.
