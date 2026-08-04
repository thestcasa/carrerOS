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
