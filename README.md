# Career OS

A local, candidate-configurable, safety-gated job application control plane. The repository
contains fictional example data only. Synthetic submission is available for routine development;
the separately isolated Greenhouse final-click capability is implemented but disabled by default.

## One-command stack

```bash
docker compose up --build
```

Open the web control plane at `http://localhost:3000`; the API and OpenAPI docs are at
`http://localhost:8000` and `http://localhost:8000/docs`. Compose starts the frontend, FastAPI,
PostgreSQL, Redis, general workflow worker, isolated browser dry-run worker, and scheduler, then
applies Alembic migrations. Candidate edits and runtime artifacts use separate persistent volumes.
Services bind to localhost by default. The default stack intentionally does not start the
controlled-submission worker.

## First-version review path

Use only the fictional `example_candidate` for the first review. The dashboard presents one guided,
plain-language path through readiness, job selection, materials review, synthetic dry run, human
action, and explicit controlled approval. Only the first incomplete stage exposes the recommended
primary action; technical evidence remains available on the linked detail page.

Autonomous mode remains fail-closed. `no_tested_ats_adapter` and
`dry_run_acceptance_not_passed` must be cleared by backend evidence from synthetic acceptance
checks; they are not manual toggles. `explicit_confirmation_missing` can be cleared only by an
audited user confirmation after the other prerequisites pass. No agent may confirm it for the
user or enable a live final click.

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
npx playwright install --with-deps chromium
npm run test:e2e
```

The web interface covers candidate onboarding/CV import/readiness, discovery and analysis,
application materials, synthetic dry runs, controlled-approval queuing, human actions, security
events, settings, analytics, and a labelled viewer for each exact immutable submitted artifact.
The deterministic Playwright suite
intercepts every API request and never contacts or mutates a real provider. The CLI also provides
`onboard`, bounded local TXT/PDF/DOCX `import-cv`, deterministic
JSON/YAML `export-configuration`/`import-configuration`, fixture-safe `discover`, bounded
`export-candidate`, and recoverable `delete-candidate`/`deletion-status` commands. Configuration
transfer, lifecycle export, and irreversible deletion are distinct controls in settings; the
fictional onboarding template is protected.

See `docs/ARCHITECTURE.md`, `docs/CANDIDATE_ONBOARDING.md`, `docs/SECURITY.md`, and
`docs/OPERATIONS.md`. Career OS never bypasses CAPTCHA or anti-bot controls. No live application
was executed while building or testing this repository.

The committed CI workflow repeats backend, migration, frontend, production-build, and browser
quality gates. API/runtime operational records are structured JSON with bounded correlation and
workflow metadata; request bodies, tokens, candidate facts, and hidden prompts are not logged.
