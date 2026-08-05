# Operations

Start the local stack with `docker compose up --build`. The UI is at `http://localhost:3000`, the
API at `http://localhost:8000`, and API documentation at `/docs`. Services bind to `127.0.0.1`.
PostgreSQL, Redis, candidate data, and runtime artifacts use separate volumes.

Useful commands:

```bash
alembic upgrade head
alembic check
python -m app onboard --candidate fictional_friend --display-name "Fictional Friend"
python -m app validate-candidate --candidate fictional_friend
python -m app readiness --candidate fictional_friend
python -m app export-candidate --candidate fictional_friend
python -m app discover --candidate fictional_friend --fixture fixtures/jobs.json
```

New candidates are unapproved, blocked drafts with an `.invalid` address. Complete and approve
legal/profile/answer configuration before enabling discovery; autonomous mode has additional
tested-adapter, dry-run, and explicit-confirmation blockers. The emergency stop denies new
authorizations immediately.

Back up candidate, PostgreSQL, and runtime volumes together. Application artifacts are immutable
and hash verified. A failed hash check is a security incident: stop automation, preserve the files,
and inspect event/security ledgers.

The autonomous development environment has no Docker binary, so Compose startup must be verified
on a Docker-capable host. SQLite migrations and backend/frontend quality gates are the offline
verification path.
