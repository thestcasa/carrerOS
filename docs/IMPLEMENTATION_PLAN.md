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

## Later milestones

- Job ingestion and normalization with provenance and deduplication.
- Human review UI and explicit approval workflows.
- Restricted browser execution that consumes gate authorizations and stops at CAPTCHA/anti-bot challenges.
- Observability, retention controls, security hardening, and deployment automation.

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
