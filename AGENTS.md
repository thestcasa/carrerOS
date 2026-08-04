# Repository Guidelines

## Project Structure & Module Organization

Backend code lives in `app/`. Candidate services are under `app/candidates/`, SQLAlchemy models in `app/domain/`, and agent contracts in `app/agents/`. The Next.js/React/TypeScript control plane lives in `frontend/app/`, with shared UI in `frontend/components/` and its typed API client in `frontend/lib/`.

Fictional candidate configuration belongs in `candidates/{candidate_id}/`. Database revisions live in `migrations/`, architecture records in `docs/`, backend tests in `tests/`, and frontend tests in `frontend/tests/`. Never add real candidate data to fixtures.

## Build, Test, and Development Commands

Use Python 3.12 or newer:

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python -m app validate-candidate --candidate example_candidate
python -m app readiness --candidate example_candidate
uvicorn app.api:app --reload
```

Run `docker compose up --build` for the frontend, API, PostgreSQL, and Redis. Apply schema changes with `alembic upgrade head`; verify migration completeness with `alembic check`.

Before submitting changes, run:

```bash
ruff format --check app tests migrations
ruff check app tests migrations
mypy app tests
pytest
cd frontend
npm run lint
npm run typecheck
npm test
npm run build
```

## Coding Style & Naming Conventions

Use four-space Python indentation, complete type annotations, and a 100-character line limit. Ruff and strict mypy govern Python. ESLint and strict TypeScript govern the two-space-indented frontend. Use `snake_case` for Python functions, `PascalCase` for classes/components, and uppercase Python enum members.

Prefer strict, frozen Pydantic v2 contracts and SQLAlchemy 2 typed mappings. Every candidate-owned database record must include a non-null `candidate_id`. Keep candidate preferences and thresholds in configuration, never engine constants.

## Testing Guidelines

Use pytest for backend tests named `test_<area>.py`; use Vitest and Testing Library for `*.test.tsx`. Test failure paths and fail-closed behavior. Schema, workflow, authorization, archive, isolation, or readiness changes require regression tests. Use fictional names and `.invalid` domains.

## Commit & Pull Request Guidelines

This workspace has no Git history, so no existing convention can be inferred. Use concise Conventional Commit subjects, such as `feat: add candidate snapshot validation` or `fix: deny expired authorization`.

Pull requests should explain scope, safety impact, migrations or configuration changes, linked issues, and commands executed. Include screenshots only for visible UI changes. Never combine live-submission/browser work with unrelated foundation changes.

## Security & Architecture Boundaries

Only `SubmissionGate` may issue submission authorization. LLM workers must remain isolated and cannot submit. Never bypass CAPTCHA, evade anti-bot controls, expose secrets, fabricate claims, or add hidden ATS manipulation. Missing or uncertain information must deny submission.

# Autonomous build protocol

When assigned an autonomous build:

1. Read `carreros_project_spec` as the authoritative source of truth.
2. Read all applicable architecture, implementation, milestone, and task documentation.
3. Inspect Git status, the current implementation, tests, migrations, and existing conventions.
4. Determine the next incomplete milestone or acceptance criterion.
5. Create or update:
   - `docs/AUTONOMOUS_BUILD_PLAN.md`
   - `docs/AUTONOMOUS_STATUS.md`
6. Continue from planning through implementation, testing, repair, review, documentation, and commit.
7. Do not stop after producing a plan, summary, partial implementation, or list of next steps.
8. Do not ask the user to approve intermediate phases.
9. Resolve minor ambiguities conservatively and record the decision in the build plan.
10. Use subagents for independent exploration, test analysis, security review, and bounded implementation tasks.
11. The primary agent owns architecture, integration, shared schemas, migrations, final testing, and commits.
12. Avoid concurrent writes to the same files or tightly coupled modules.
13. Run the relevant quality gates after every meaningful implementation phase.
14. Repair failing tests, lint, typing, migration, and build checks before continuing.
15. Review the final diff for regressions, scope creep, secrets, generated files, and real personal data.
16. Commit completed milestones with clear conventional commit messages.
17. Never add real candidate data, credentials, secrets, live applications, CAPTCHA bypass, ATS manipulation, or submission authorization outside SubmissionGate.
18. If an external dependency blocks one check, document the exact blocker and continue all independent work.
19. Update `docs/AUTONOMOUS_STATUS.md` before every natural stopping point so another session can resume using repository state only.
20. Stop only when:
    - all requirements in `carreros_project_spec` are complete and verified; or
    - a hard external blocker prevents all further useful progress.

At successful completion, end the final response with exactly:

BUILD_COMPLETE

If a hard blocker prevents all further work, end with exactly:

BUILD_BLOCKED