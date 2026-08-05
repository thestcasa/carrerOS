# Autonomous Build Plan

## Objective

Implement and verify the complete definition of done in `CareerOS_PROJECT_SPEC(1).md` from
the current repository state. Preserve the deterministic `SubmissionGate` boundary, candidate
isolation, immutable history, truthful provenance, and the prohibition on live applications,
CAPTCHA bypass, ATS manipulation, employer contact, and committed real candidate data.

## Repository baseline

- Branch: `autonomous-build`.
- Milestone 1 is substantially complete: strict fictional candidate configuration, readiness,
  snapshots, candidate APIs and core UI, candidate-scoped persistence, state machine, isolated
  agent contracts/fakes, deny-by-default gate, immutable archive skeleton, and local stack shell.
- The authoritative spec's Milestones 2–8 and most full-product acceptance tests remain.
- Existing local changes in `scripts/run-autonomous-build.sh` and `artifacts/` predate this build;
  they are user-owned and excluded from implementation commits.
- The inherited worktree contains uncommitted, passing foundations for discovery, materials,
  synthetic browser dry runs, operations, correspondence, and local-auth primitives. These are
  preserved and integrated instead of recreated.
- The current runtime is Python 3.14.4. The previously recorded FastAPI `TestClient` hang no
  longer reproduces: the complete 87-test backend suite passes.
- Docker is unavailable in this environment. The Python Playwright package is installed, but this
  minimal host lacks a usable Chromium runtime and its shared libraries. The container image now
  installs Chromium with its dependencies; that path requires verification on a Docker-capable
  host.
- The specification contains real pilot data, but repository safety rules prohibit committing
  it. Pilot behavior will be proven with fictional configuration and documented onboarding
  blockers rather than copying personal data into version control.

## Execution order

### Phase 1 — Milestone 2: discovery, analysis, and jobs inbox

1. Add versioned normalized job contracts and persistence without breaking Milestone 1 data.
2. Add deterministic URL/domain validation, prompt-injection scanning, description
   normalization, duplicate fingerprints, and candidate application duplicate hashes.
3. Add Greenhouse, Lever, and Ashby adapters behind an allowlisted adapter protocol. Tests use
   deterministic fixtures; no live provider access is required.
4. Add candidate-configured classification, salary checks, hard blockers, dimensional scoring,
   bonuses/penalties, evidence, and distinct per-candidate results.
5. Add candidate-aware job repositories and APIs for discovery, list/detail, verify, analyze,
   shortlist, and skip with idempotency and stable error codes.
6. Add `/jobs` inbox/detail pages, discovery status/controls, evidence, blockers, freshness,
   security findings, and score explanations. No bulk submission.
7. Add worker/scheduler process boundaries and persistent runtime volumes to Compose.

### Phase 2 — Milestone 3: materials and preview

1. Implement approved-fact selection, claim provenance, CV/cover-letter/answer generation,
   templates, deterministic rendering and validation, and independent semantic review.
2. Persist immutable draft versions and manual edits without overwriting history.
3. Add material preview, download, provenance, validation/review, and version UI.

### Phase 2A — integration and tenant-safety repair

Before expanding UI surface area, close the cross-cutting gaps exposed by the baseline audit:

1. Bind every candidate-owned child record to the same candidate as its parent at the database
   boundary and add adversarial isolation regression tests.
2. Persist one-time submission authorization consumption so process restarts cannot replay a
   final submission.
3. Wire local session ownership, CSRF checks, stable idempotency, and rate limiting into the API;
   never trust a query/body `candidate_id` without matching authenticated scope.
4. Build a persistence-backed application service that integrates materials, human actions,
   security events, settings, analytics, correspondence, artifacts, and audit history.

Status: tenant constraints, durable authorization, local auth/CSRF, applications, human actions,
security, settings, analytics, and artifacts are integrated. Correspondence remains the next item.

### Phase 3 — Milestone 4: browser dry run and human action

1. Add a restricted Playwright worker and synthetic ATS fixture server.
2. Add candidate-isolated persistent sessions, field mapping, allowlisted uploads, final-page
   extraction, CAPTCHA/OTP detection, and human actions. Synthetic runs never click a real final
   submit control.
3. Add human-action APIs and queue/takeover UI with same-session resumption.

Status: a restricted Playwright fixture harness and loopback-only synthetic ATS fixture server are
implemented. It uses candidate-isolated persistent profiles, hash-verified uploads, DOM field
readback, human-action detection, and permits exactly one allowlisted GET document request per run;
all later requests, WebSockets, service workers, redirects, and form submissions are blocked. It
has no final-submit click operation. The application workflow is not yet wired to this harness.
Human completion now defaults to denial unless a browser-owned same-session verifier is injected;
the local API handshake alone cannot clear the challenge. Contract tests pass; the actual Chromium
test is skipped on this host, and the Docker execution path and interactive transport remain open.

### Phase 4 — Milestones 5 and 6: controlled submission and operations

1. Complete the required pre-submit archive and one-time, short-lived authorization consumption.
2. Implement only synthetic/test submission execution in this build unless a separately
   authorized safe environment exists; never submit a live application.
3. Add confirmation-aware application detail/pipeline, exact artifact viewers, notifications,
   rate limits, approval/autonomous modes, emergency stop, settings, dashboard, and analytics.
4. Prove the UI cannot claim success without backend confirmation and cannot enable autonomy
   while readiness is blocked.

Status: synthetic-only submission, archives, one-time authorization, primary operational routes,
both frontend safety regression tests, notifications, transactional rate limits, durable task
scheduling, and administrative audit are complete.

Hardening update: confirmation evidence is backend-owned, authorization claiming is an atomic
conditional update with durable replay, denied gate preflights do not seal orphan archives, exact
required submitted documents fail closed, and successful runs create a copy-on-write confirmed v2
archive while preserving the pre-submit v1 archive.

### Phase 5 — Milestones 7 and 8: correspondence and hardening

1. Add provider-neutral correspondence ingestion/classification with deterministic Gmail
   fixtures, status updates, correspondence UI, and interview packages. No automatic replies.
2. Add local authentication, tenant-aware authorization, encrypted secret interfaces,
   candidate export/deletion, signed artifact access, administrative audit, CSRF/session/rate
   protections, and isolated worker ownership needed before hosted deployment.

Status: correspondence persistence/classification/state integration, notifications, immutable
interview packages, local session ownership/CSRF, tenant constraints, artifact authorization,
exports, and administrative audit are complete. Rich onboarding, executable deletion/retention,
hosted encryption, and separate Playwright worker ownership remain.

### Phase 5A — candidate fact controls and portable data

1. Extend candidate packages with fact-level approval, verification, confidentiality, archive,
   and document-eligibility controls while loading older packages conservatively.
2. Add optional certification, publication, and secret-free notification-rule domains to the
   loader, snapshot, versioned editor, fictional fixture, and readiness model.
3. Derive generation inputs only from approved public facts. Internal, archived, unverified,
   expired, and non-auto-submit data must never reach outward material generation.
4. Keep onboarding drafts empty and unapproved instead of copying approved fictional evidence.
5. Add deterministic CV-import draft extraction and explicit approval workflow without storing
   or committing real candidate documents.

Status: all five steps are implemented. CV import accepts bounded UTF-8 text, stores only a
hash and structured extraction draft, applies education/experience atomically as restricted and
unapproved facts, and blocks readiness pending explicit review. API, CLI, profile UI, idempotency,
and failure-path tests are included. PDF parsing is deferred until a resource-isolated document
worker exists.

### Phase 6 — definition-of-done verification

1. Audit all 24 acceptance criteria and mandatory zero-tolerance safety targets.
2. Verify Alembic upgrade/check, backend format/lint/type/tests, frontend lint/type/tests/build,
   integration/security/browser/accessibility tests, fictional local workflow, and Compose when
   Docker is available.
3. Review the complete diff for regression, secrets, generated files, personal data, and scope.
4. Update architecture, setup, operations, onboarding, security, adapter, and status documents.
5. Commit only coherent passing milestones with Conventional Commit subjects and finish with a
   clean working tree apart from preserved pre-existing user changes.

## Conservative decisions

- External HTML and job text always remain untrusted data; adapters only extract structured
  fields and cannot invoke tools or alter policy.
- Missing or ambiguous values fail closed and create blockers or human actions.
- All network-facing provider behavior is exercised through deterministic fixtures unless a
  read-only provider call is explicitly safe and necessary.
- Backend validation and state are authoritative; the frontend never duplicates submission
  authorization logic or optimistically reports success.
- Major schema/API changes are migration-backed and backward-compatible where practical.
- Missing optional candidate files load as unconfigured domains. Missing approval metadata always
  defaults to false; compatibility never silently upgrades a legacy fact to approved.
- The specification's named pilot data is not copied into version control because the repository
  instructions explicitly prohibit real candidate data. Pilot readiness is represented as an
  onboarding/configuration task and all executable acceptance paths use fictional `.invalid`
  identities.

## Quality gates per coherent slice

```text
ruff format --check app tests migrations
ruff check app tests migrations
mypy app tests
pytest
alembic upgrade head
alembic check
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

Relevant focused tests run first after each edit; the full set runs before every milestone commit.
