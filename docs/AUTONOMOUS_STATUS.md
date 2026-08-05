# Autonomous Build Status

## Current state

- Build status: **IN PROGRESS**
- Active phase: deletion/retention design, productionization gaps, and final verification
- Branch baseline: `autonomous-build`; latest completed milestone is active-candidate propagation
- Authoritative specification: `CareerOS_PROJECT_SPEC(1).md` version 1.1.0
- Preserved user-owned workspace items: `scripts/run-autonomous-build.sh` and `artifacts/`

## Implemented and integrated

- Strict fictional candidate configuration, onboarding into an unapproved blocked draft,
  validation/readiness/snapshots, all-section editing, version history, import/export, API, CLI,
  candidate selector/editor/readiness UI.
- Greenhouse, Lever, and Ashby fixture adapters; HTTPS/domain validation, append-only job versions,
  duplicate fingerprints, durable discovery/job command receipts, prompt-injection quarantine and
  candidate security events, configuration-driven scoring, inbox/detail APIs and UI.
- Three correlation-checked isolated agent contracts, deterministic evidence-backed material
  generation, provenance, wrong-company/unsupported-claim validation, independent review, and
  immutable versioned draft persistence.
- Persistence-backed application workflow from scored job through materials, approval, synthetic
  form fill, CAPTCHA/OTP human action, final validation, deterministic gate, durable one-time
  authorization, synthetic confirmation, exact artifacts, events, pipeline/detail UI.
- Candidate-isolated synthetic browser sessions with allowlisted hash-verified uploads, persisted
  page snapshots/screenshots, no submit capability, and same-session human-action resume.
- Specification-shaped immutable archive with candidate/job/scoring evidence, exact PDF document
  bytes, answers, captures, receipt, JSONL audit ledgers, recursive SHA-256 verification, and
  authenticated downloads.
- Database-enforced same-candidate composite relationships, local bearer/CSRF enforcement,
  backend-authoritative confirmation/autonomy UI, emergency stop, settings, analytics, security,
  dashboard, signed-token/admin-audit/export/deletion planning foundations.
- Provider-neutral correspondence is persisted and associated fail-closed; interview/rejection/
  offer messages update valid states, create dashboard notifications, appear in application detail,
  and generate immutable interview packages from exact application evidence.
- SQL-backed workflow tasks provide idempotent scheduling, row leases, expired-lease recovery,
  bounded retries, and real worker handling for periodic candidate readiness checks.
- Candidate settings/security mutations have a persistent hash-chained administrative ledger;
  application rate limits and emergency stop are checked at authorization and execution time.
- Candidate records now expose explicit approval, archive, confidentiality, verification, and
  document-eligibility controls. Certifications, publications, and secret-free notification rules
  are optional, versioned domains in the API/editor/snapshot. Generation filters out internal,
  unapproved, archived, unverified, expired, and non-auto-submit material at the derivation boundary.
- Fictional onboarding creates an empty unapproved evidence draft rather than inheriting approved
  facts from the example candidate. Readiness checks fact approvals, sensitive answers, document
  rules, availability, legal verification, and configured optional domains.
- Synthetic confirmation is backend-owned rather than caller-asserted. Authorization consumption
  is claimed atomically and matching command retries replay the durable outcome. Confirmed
  applications create a verified copy-on-write v2 archive with confirmation HTML, screenshot,
  receipt, final manifest, and refreshed audit while preserving the pre-submit v1 archive. Gate
  denials occur before archive sealing and missing exact submitted documents fail closed.
- A restricted Playwright fixture harness now targets an exact allowlisted loopback URL, uses
  isolated persistent browser profiles, validates uploads by candidate path and SHA-256 allowlist,
  captures screenshots and HTML, and never exposes a final-submit click. It permits only the first
  GET document request and blocks every later request, WebSocket, redirect, or form submission.
- Human-action completion requires a prior explicit session-open handshake and a separate
  browser-owned same-session verifier. The verifier defaults to denial; a database handshake alone
  cannot advance an application to final validation.
- Candidate onboarding now includes bounded local UTF-8 CV extraction through API, CLI, and the
  profile UI. Raw documents are not retained; deterministic education/experience drafts carry the
  source hash, restricted confidentiality, and false approvals. Applying a draft creates one
  version atomically and blocks readiness until explicit review.
- PDF parsing remains denied until it can execute in a CPU/memory/time-constrained worker.
- Candidate selection now persists as a validated same-site cookie. The dashboard, navigation,
  operational list routes, and job/application detail routes consistently use the query override or
  active candidate instead of silently hardcoding the fictional example profile.

## Latest verification

- Backend: `ruff format --check`, Ruff lint, strict mypy, and **122 pytest tests pass** on Python
  3.14.4. The actual Chromium test reports one explicit skip because no Playwright browser is
  installed in the host cache; one upstream Starlette `httpx` deprecation warning remains.
- Frontend: ESLint, strict TypeScript, **26 Vitest tests**, and the Next.js production build pass
  for all required routes.
- Migrations: fresh SQLite upgrade and `alembic check` pass through `a71c302de864`; models and
  Alembic report no missing operations.
- Docker is not installed in this environment. PostgreSQL/Redis/Compose startup and the container's
  Playwright Chromium path remain externally unverified. The image installs Chromium and system
  dependencies with `playwright install --with-deps chromium`.
- No live applications, employer contact, CAPTCHA bypass, ATS manipulation, committed credentials,
  or real candidate fixture data were introduced.

## Remaining definition-of-done gaps

- Verify the real Playwright synthetic fixture test in the Docker image; no real final clicks are
  authorized in this repository. Add a deployment-specific interactive transport before claiming
  production same-context human takeover, and wire the fixture harness through the isolated
  application worker boundary. The local API currently performs only a validated session handshake.
- Execute export/deletion and retention workflows; hosted authentication/encryption and separate
  browser workers remain deployment hardening.
- Add browser E2E/accessibility-critical suites and run PostgreSQL/Compose checks on a capable host.
- Audit every final acceptance criterion, finish docs, commit each coherent slice, and leave the
  worktree clean apart from the two preserved user-owned paths.

## Resume instructions

1. Read `docs/AUTONOMOUS_BUILD_PLAN.md` and this file.
2. Inspect Git status and do not stage `scripts/run-autonomous-build.sh` or `artifacts/`.
3. Continue discovery/material productionization or deletion with a durable tombstone and writer fence.
4. Run backend, migration, and frontend gates after each coherent phase.
