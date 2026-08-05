# Implementation Plan

## Milestones 0 and 1: safe foundation and candidate control plane

1. Bootstrap a Python 3.12 project with application packaging, FastAPI health endpoint, SQLAlchemy session factory, Alembic, PostgreSQL Docker Compose, and lint/type/test configuration.
2. Model every candidate configuration document with strict Pydantic v2 schemas. Build a traversal-safe loader, manifest/version validation, deterministic snapshots, readiness reporting, and CLI commands.
3. Add SQLAlchemy 2 domain models with candidate isolation constraints and an initial Alembic migration.
4. Implement the typed application state machine, transition allow-list, failure semantics, and idempotency behavior.
5. Define isolated agent protocols and request/response contracts. Supply deterministic, stateless fake implementations for orchestration and tests.
6. Implement the fail-closed deterministic submission gate and gate-issued authorization.
7. Implement immutable application archive creation and hash verification.
8. Add fictional candidate fixtures and focused tests for the safety and correctness cases named in the specification.
9. Run Ruff formatting/checking, mypy, and pytest. Resolve all Milestone 1 failures.
10. Add PostgreSQL and Redis health probes plus stable, typed candidate APIs.
11. Add versioned core-profile updates which reuse strict candidate validation.
12. Build the Next.js candidate selector, profile editor, and capability-specific readiness
    page with lint, type, component-test, and production-build checks.
13. Run the frontend, API, PostgreSQL, and Redis as a health-ordered Compose stack available
    at `localhost:3000`.

## Milestone 2: discovery and analysis

The exact next milestone is **Milestone 2 — Discovery, Analysis, and Jobs Inbox** from the
master specification: Greenhouse, Lever, and Ashby discovery; normalized versioned jobs;
duplicate detection; security scanning; the provider-backed `JobAnalysisAgent`;
candidate-configured scoring; fictional pilot company seeds; discovery controls/status; a
jobs inbox; and a job-detail view with evidence, score, blockers, salary, and source
verification. It also introduces PostgreSQL repositories and durable scheduling. It does
not add browser automation or live submission.

### Milestone 2 progress

- [x] Strict normalized discovery contracts and fixture-backed Greenhouse, Lever, and Ashby
  payload adapters.
- [x] HTTPS/domain allowlisting, prompt-injection scanning, semantic fingerprints, and
  candidate-scoped duplicate hashes.
- [x] Append-only job versions and expanded normalized job persistence with Alembic migration.
- [x] Candidate-configured deterministic classification, scoring, hard blockers, and evidence.
- [x] Candidate-aware discovery/list/detail/analyze service and initial jobs inbox/detail UI.
- [x] Persist job-command idempotency receipts and candidate inbox decisions.
- [x] Add verification, shortlist, skip, and discovery controls/API actions.
- [x] Add worker/scheduler process boundaries and Redis heartbeat coordination.
- [x] Add durable discovery receipts, persisted injection events, and passing API/frontend
  contract coverage under the available Python 3.14 runtime.

## Milestone 3 and later

- [x] Deterministic approved-fact generation, provenance, validation/review, and immutable draft
  artifact backend foundation.
- [x] Persist material metadata through the application API and complete preview/version UI.
- [x] Synthetic restricted browser dry-run contracts that stop at CAPTCHA/OTP and cannot click.
- [x] Persist synthetic browser sessions/screenshots/human actions and complete queue/resume UI.
- [x] Add synthetic one-time submission authorization consumption, emergency stop, rate limits,
  autonomy guard, backend confirmation truthfulness, notifications, digest, and analytics.
- [x] Add provider-neutral correspondence classification and interview-package foundations.
- [x] Add signed local sessions/artifacts, candidate ownership, CSRF, administrative audit, and
  export/deletion planning foundations.
- [x] Integrate materials, synthetic application workflow, artifacts, human actions, security,
  settings, analytics, local auth, and the primary required web routes.
- [x] Add a persistent workflow queue and correspondence/notification/interview integration.
- [x] Add a network-denied Playwright fixture harness and bounded unapproved CV import workflow.
- [x] Render and structurally validate versioned PDFs before approval, upload their exact hashes,
  and archive the same bytes without lossy rerendering.
- [x] Schedule candidate-owned public ATS sources through bounded read-only transports and durable
  leased discovery tasks with freshness/error status.
- [x] Execute bounded candidate export, durable deletion/recovery, writer fencing, and configurable
  browser-profile retention.
- [ ] Complete isolated Playwright application integration, portable-export import, and hosted
  security.
- [ ] Add PostgreSQL/Compose, browser E2E, and automated accessibility verification when those
  external runtimes are available.

## Acceptance criteria for Milestone 1

- Both candidate CLI commands return machine-readable reports and meaningful exit codes.
- Candidate configuration has no engine-level candidate preferences.
- Every candidate-owned database model carries `candidate_id`.
- Invalid and terminal state transitions fail deterministically; idempotent replay is safe.
- Agent messages validate strictly and fake workers share no mutable context.
- The gate denies on any missing requirement and no other component issues authorization.
- Archive verification detects mutation.
- Required tests, Ruff, and mypy pass.
- Candidate APIs preserve isolation and version history.
- The responsive frontend exposes selection, editing, and capability-specific readiness.
- The local stack starts with one Compose command and reports service health.
