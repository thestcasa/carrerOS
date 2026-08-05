# Career OS

A local, candidate-configurable, safety-gated job application control plane. The repository
contains fictional example data only; submission execution is restricted to the bundled synthetic
fixture.

## One-command stack

```bash
docker compose up --build
```

Open the web control plane at `http://localhost:3000`; the API and OpenAPI docs are at
`http://localhost:8000` and `http://localhost:8000/docs`. Compose starts the frontend, FastAPI,
PostgreSQL, Redis, workflow worker, and scheduler, then applies Alembic migrations. Candidate edits
and runtime artifacts use separate persistent volumes. Services bind to localhost by default.

## Local setup

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python -m playwright install --with-deps chromium
alembic upgrade head
python -m app validate-candidate --candidate example_candidate
python -m app readiness --candidate example_candidate
pytest
```

For frontend development:

```bash
cd frontend
npm ci
npm run dev
npm run lint
npm run typecheck
npm test
npm run build
```

The web interface covers candidate onboarding/CV import/readiness, discovery and analysis, application
materials and synthetic dry runs, human actions, security events, settings, analytics, and exact
immutable artifact downloads. The CLI also provides `onboard`, local `import-cv`, fixture-safe
`discover`, bounded `export-candidate`, and recoverable `delete-candidate`/`deletion-status`
commands. Candidate export and irreversible deletion are also available from settings; the
fictional onboarding template is protected.

See `docs/ARCHITECTURE.md`, `docs/CANDIDATE_ONBOARDING.md`, `docs/SECURITY.md`, and
`docs/OPERATIONS.md`. Career OS never bypasses CAPTCHA or anti-bot controls, and this build
contains no live final-click capability.
