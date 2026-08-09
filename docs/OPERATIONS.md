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

Controlled submission is deliberately outside the default stack. Enabling it requires the exact
same `CONTROLLED_SUBMISSION_ENABLED=true` process setting on the API and scheduler plus a separately
started isolated worker:

```bash
CONTROLLED_SUBMISSION_ENABLED=true python -m app run-controlled-submission-worker
```

That switch is necessary but insufficient. Candidate source configuration must explicitly enable
automatic submission; settings must use `approval_required` or a blocker-free `autonomous` mode;
Greenhouse must be both allowed and tested; and every fresh gate, package, duplicate,
browser-session, emergency-stop, and rate-limit check must pass. Do not start this worker merely to
run tests. Unit and integration tests use fictional in-process executors and never contact an ATS.
CAPTCHA, OTP, or an unsupported visible control stops before authorization consumption and creates
a human action. A denied pre-click attempt may be tried again only through a new explicit
authorization after the cause is resolved; autonomous scheduling never retries it. Once the click
boundary is armed, every missing/ambiguous result is terminal `UNKNOWN_AFTER_CLICK` and must not be
retried.

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
authorizations and pre-click arming immediately. An already armed click is recorded durably and is
never retried; ambiguous outcomes require human investigation.

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

The scheduler enqueues a retention/expiry sweep every 15 minutes.
`browser_session_retention_days` defaults to 30
and is configurable from 1 to 3650 in settings. Eligible confirmed/cancelled/ready sessions and
expired human-takeover profiles are quarantined, committed as retained metadata, then removed.
Expired human actions return their application to form filling with an audit event as soon as a
sweep observes their deadline; their profile is removed only after its separate retention age.
Submitted
immutable archives are retained until intentional candidate deletion.

### Recover stale fictional candidate data

The persistent candidate volume can mask a newer repository fixture after a schema change. Do not
use `docker compose down -v`: it deletes unrelated persistent state. Every backend container now
compares the mounted `example_candidate` with the immutable image fixture before starting. The
report contains tree hashes and changed paths, never candidate field values, and a difference does
not mutate or block a customized but structurally safe volume:

```bash
docker compose exec -T api python -m app inspect-candidate-volume
```

To review the pristine fixture without touching the candidate volume, stage an absent recovery copy
under the runtime volume. The command fails if the destination already exists:

```bash
docker compose exec -T api python -m app stage-candidate-recovery \
  --destination-root /app/runtime/recovery-review
docker compose exec -T \
  -e CANDIDATES_ROOT=/app/runtime/recovery-review \
  api python -m app validate-candidate --candidate example_candidate
```

The staged copy is for explicit diff and migration review. For a clean new draft, use
`python -m app onboard` with a new candidate ID. Docker
onboarding reads the immutable image fixture, so stale mounted example data cannot seed the new
candidate. Export and back up any private or unknown candidate before an explicit schema migration
or reviewed manual correction. Never copy the fixture over a mounted candidate. An experience item
without `end_date` is valid only when `current: true`.

Back up candidate, PostgreSQL, and runtime volumes together. Application artifacts and browser
attempt evidence are immutable and hash verified. A failed hash check is a security incident: stop
automation, preserve the files, and inspect event/security ledgers. Synthetic confirmation does
not fabricate a screenshot; its receipt explicitly reports that no confirmation screenshot is
available.

Controlled confirmation stores exact pre-click and confirmation PNG/HTML evidence, a
copy-on-write v2 archive, and a backend-confirmed receipt. If confirmation is absent, the
application is visibly `UNKNOWN_AFTER_CLICK` and the UI says “do not retry.”

The scheduler collision `idempotency key was used for a different task` is repaired and covered by
regression tests for retained historical tasks and profile-version changes. On 2026-08-09 the full
backend suite passed 333 tests, including the 20-case real Chromium synthetic-form matrix. The
committed frontend Playwright route/safety/accessibility suite passed 13/13 with every provider
request intercepted.

Fresh Compose verification could not be executed in the current WSL session. `/usr/bin/docker` is
a dangling link to `/mnt/wsl/docker-desktop/cli-tools/usr/bin/docker`, while `/mnt/wsl` is absent;
`docker compose version` therefore returns `docker: command not found`. The Compose YAML parses as
seven services, but that is not a health result. The older successful stack observation above must
not be treated as verification of this revision. Reconnect Docker Desktop's WSL integration, then
run `docker compose up --build`, wait for every default service (including scheduler) to remain
healthy across repeated cycles, and rerun `npm run test:e2e` without enabling the controlled worker.
