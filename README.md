# Career OS

Milestone 1 of a candidate-configurable, safety-gated job application platform. The
repository contains fictional example data only.

## One-command stack

```bash
docker compose up --build
```

Open the web control plane at `http://localhost:3000`; the API and OpenAPI docs are at
`http://localhost:8000` and `http://localhost:8000/docs`. Compose starts the frontend,
FastAPI, PostgreSQL, and Redis, then applies Alembic migrations. Candidate edits are
persisted in a named volume and create version history.

## Local setup

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
python -m app validate-candidate --candidate example_candidate
python -m app readiness --candidate example_candidate
pytest
```

For frontend development:

```bash
cd frontend
npm install
npm run dev
npm run lint
npm run typecheck
npm test
npm run build
```

See `docs/ARCHITECTURE.md` for component and trust boundaries. Live applications,
Playwright submission, CAPTCHA handling, and ATS manipulation are not implemented.
