# Autonomous Build Status

## Current state

- Build status: **IN PROGRESS - FIRST-VERSION UX AND AUTONOMY READINESS**
- Active phase: local Docker demo stabilization and guided user-pipeline simplification; external
  pilot, secure takeover transport, and Gmail/OAuth work remain separate blockers
- Branch baseline: `autonomous-build`; CORS and reliable Docker health fixes are published through
  `90cfb31`
- Authoritative specification: `CareerOS_PROJECT_SPEC(1).md` version 1.1.0
- Preserved user-owned workspace items: `scripts/run-autonomous-build.sh`, `artifacts/`, and the
  later untracked root file `how d8c72b0`

## Immediate local TODO - first-version UX and autonomy readiness

- Simplify the normal website journey into one guided pipeline: candidate readiness, job selection,
  material generation/review, safe dry run, human-action resolution, and explicit controlled approval.
  Each page should expose one primary next action and link directly to the blocker it can resolve.
- Use progressive disclosure: show plain-language status, consequences, and next actions by default;
  keep hashes, internal IDs, raw policy fields, and advanced controls in expandable detail.
- Replace raw autonomy blocker identifiers with user-facing explanations, current evidence, and a
  concrete action. Preserve backend authority and fail-closed behavior.
- Resolve `no_tested_ats_adapter` only from a recorded passing synthetic acceptance run for the exact
  adapter/form pattern. Do not provide a manual checkbox that can claim untested evidence.
- Resolve `dry_run_acceptance_not_passed` only from candidate-scoped passing dry-run evidence and the
  committed browser acceptance suite. Do not let the user self-declare the test passed.
- Add an explicit, unchecked autonomy confirmation step only after all evidence prerequisites pass.
  Explain scope, rate limits, emergency stop, and consequences; persist an administrative audit event.
  The agent must not confirm autonomy on the user's behalf.
- Keep `approval_required` as the first-version default and keep live controlled submission disabled at
  the process boundary during development and automated verification.
- Add component, route, accessibility, and backend tests for the guided path and every blocker action.
- Repair the scheduler's durable task idempotency collision
  (`idempotency key was used for a different task`) and prove it remains running across repeated
  scheduling cycles.

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
- Controlled Greenhouse execution is implemented as a separate, default-disabled trust zone. Its
  dedicated worker is absent from default Compose and refuses startup without a process switch.
  Candidate policy, emergency stop, rates, task lease, source freshness, duplicate identity,
  browser session, current package, target, and form fingerprint are rechecked immediately before
  a transaction consumes authorization and records immutable boundary evidence. `SubmissionGate`
  then issues a short-lived one-use in-memory permit for exactly one same-origin POST. Confirmation
  archives the exact final page; any post-boundary ambiguity becomes terminal
  `UNKNOWN_AFTER_CLICK`, opens a human action, and is never retried. Approval and autonomous modes
  use the same durable queue/gate path. The executor repopulates and rechecks exact snapshot-derived
  identity values and the hash-verified reviewed CV after reopening the profile, while rejecting
  every unsupported visible form control. All tests use deterministic fakes without live contact.
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
- Versioned, allowlisted PDF rendering now occurs before material approval. Page limits, complete
  text extraction, supported glyphs, safe URLs, fixed layout, and source/output hashes fail closed.
  The synthetic browser uploads that exact candidate-scoped PDF, the gate re-verifies it, and the
  archive copies the same bytes without archive-time rerendering or truncation. Rendered drafts and
  reports are downloadable with template, snapshot, page, and extraction metadata. Submission
  authorizations are bound to the reviewed versions, browser hash, candidate snapshot, and verified
  archive manifest, and that package digest is reconstructed immediately before consumption.
- Candidate-owned Greenhouse, Lever, and Ashby discovery sources now run through durable cadence
  tasks. The read-only provider client enforces exact HTTPS endpoints, no redirects, bounded JSON
  responses with absolute deadlines, stable errors, and job-count limits. Missing settings and
  empty adapter allowlists deny execution. Runs persist freshness and counts; source mutations and
  retries use payload-bound receipts, transaction-level lease fences prevent superseded worker
  side effects, unchanged postings do not create versions or scores, and injection findings remain
  quarantined. Jobs and settings surfaces separate schedules from manual fixture import.
- Candidate lifecycle controls now produce a bounded portable export, execute deliberate deletion,
  and retain a minimal payload-bound deletion receipt. The filesystem marker is installed inside
  the tombstone transaction; marker-only crash states and durable failed receipts are both
  recoverable. SQLite/PostgreSQL writer triggers fence every candidate-owned table; cross-process
  lifecycle locks serialize publishers, exports, scheduler work, and deletion; and API/UI/CLI
  recovery can resume an interrupted operation. Raw candidate administrative audits are erased,
  while deletion events use a local keyed pseudonym. Configurable browser-profile retention also
  handles expired human-takeover sessions and moves their applications to an auditable retry state.
- Every candidate configuration mutation now requires a payload-bound command key. A private
  pending/completed filesystem journal preserves exact create, update, snapshot, CV-extraction,
  and CV-application results and reconciles interruption after version publication. Application
  workflow, correspondence, human-action, security, and interview mutations use durable SQL
  receipts; the frontend retains keys across uncertain failures.
- Candidate applications now store both the exact specification duplicate hash and a stronger
  candidate-scoped submission identity based on requisition ID, canonical official application
  URL, or the normalized fallback. A database constraint prevents equivalent cross-source jobs
  from racing into separate applications; missing identity denies authorization and execution.
- Job verification now refetches an exact allowlisted Greenhouse, Lever, or Ashby feed and records
  open/closed/error evidence with source payload and destination hashes. Generation,
  authorization, and synthetic submission each revalidate at their own boundary; failed evidence
  commits independently while the protected mutation remains unchanged. Job views expose stale
  and possible-duplicate state, and completed command replays do not refetch.
- Generated CV and cover-letter drafts now expose real versioned preview data, exact source-fact
  provenance paths, render/template/snapshot metadata, and independent-review results in the
  application UI. A labelled inline editor appends a new version without overwriting history.
  Backend validation accepts only the canonical job heading and exact approved-snapshot facts,
  derives provenance and actor identity server-side, verifies the base report and unchanged peer
  renders, then re-renders and re-reviews the complete package. Stale, cross-candidate, tampered,
  unsupported, no-op, and post-approval revisions deny without creating a new version.
- Candidate source configuration now has a dedicated strict JSON/YAML portability envelope with a
  canonical hash and bounded parser. Whole-configuration imports are candidate-bound, optimistic,
  payload-idempotent, rollback-safe, and publish at most one profile version. They preserve local
  active/workflow switches and cannot restore database workflow, archives, browser profiles,
  secrets, command receipts, or deletion state. API, CLI, and settings controls remain explicitly
  separate from the full lifecycle export.
- Browser dry runs now execute only through a dedicated durable worker task. Queue publication and
  workflow state are atomic, browser activity is outside SQL, and finalization rechecks the exact
  lease before committing task completion and application state together. The general worker uses
  a disjoint kind allowlist. Each attempt retains categorized retry evidence and publishes exact
  immutable PNG, HTML, and a strict manifest binding task/session/profile/URL/fields/upload hashes,
  network counts, and `submit_clicked=false`. Stale workers cannot mutate application state;
  retryable failures are bounded; terminal or exhausted work creates a human action and
  notification. Gate authorization and archives hash-check those exact files. The application UI
  polls durable queued/retrying state without offering duplicate dry-run commands, and synthetic
  confirmation no longer fabricates a placeholder screenshot.
- Browser execution and evidence publication are fenced against candidate deletion. Executor
  outputs must use exact session-relative screenshot/HTML paths opened with `O_NOFOLLOW`, stale
  attempt evidence is discarded after lease loss, and immutable attempt evidence is included in
  bounded candidate lifecycle exports.
- Runtime job analysis now invokes a provider-neutral `JobAnalysisAgent` implementation with a
  minimal candidate scoring projection. Candidate/job/policy/version hashes, exact semantic
  agreement, and strict correlation are required before service-owned provider/model/prompt
  metadata is persisted. A candidate lifecycle fence prevents profile/deletion drift while
  deterministic recomputation remains authoritative for classification, blockers, score,
  threshold, and proposed action. Injection-blocked jobs never invoke the agent, and failures or
  mismatches persist no partial analysis.
- Discovery UI mutations retain their idempotency key across uncertain manual-discovery,
  source-create, and source-toggle responses and rotate it only after backend confirmation.
- The complete normalized-job schema is strict, versioned, persisted, and exposed through the API
  and job detail. Provider-explicit company stage/team, normalized location, employment/seniority,
  skills/languages, experience ranges, salary evidence/period, authorization constraints,
  deadline, and expected start remain null when absent rather than being inferred. Migration
  `9c4e2a7b6d10` adds the previously missing database columns.
- Material generation now ranks approved experience and projects against the exact job, enforces
  configured CV/cover selection caps, chooses an allowlisted role-specific template, and records
  the selected IDs. Cover-letter inclusion has an explicit source/config/priority/motivation reason,
  configured word bounds, exact claim provenance, and evidence-safe canonical prose. The immutable
  application snapshot drives regeneration, while `Application.material_policy` persists the
  decision plus exact job version/hash for the API/UI, gate, archive, and later revisions even if
  current candidate settings later change. Missing or malformed policies deny rather than omitting
  a cover letter. Migration `4e8b1c2d3f40` conservatively marks legacy applications with existing
  cover letters.
- Application answers are append-only and snapshot-bound. Generation, manual editing, and removed
  prompts append exact version/hash/actor/predecessor records; a composite self-reference prevents
  cross-candidate, cross-application, or cross-question lineage and database triggers reject row
  updates or non-erasure deletes. Review records bind exact active answer IDs, versions, hashes,
  and snapshot IDs. Manual
  text receives approved provenance only when it exactly matches the snapshot-approved answer for
  that question; otherwise review fails closed. Gate/archive consumers use only the active latest
  revision, prompt withdrawals cannot resurrect older text, detail/UI retains immutable history,
  and interview preparation reads the hash-verified submitted-answer archive.
- The application detail now presents a dedicated, fail-closed exact submitted-package viewer for
  immutable submitted CV, cover letter, answers, and the v2+ final receipt. Each card exposes its
  exact ID, version, SHA-256, content type, and backend confirmation. PDF bytes download by exact
  artifact ID; JSON/HTML is shown only as escaped inert text, and drafts are never promoted.
- The frontend now has host-runnable axe checks plus an 11-test Playwright route/safety/accessibility
  suite with deterministic API interception. Suite discovery passes and fixtures use only
  fictional data. Chromium downloaded successfully under `/tmp`, but the minimal host cannot
  launch it because `libnspr4.so` is unavailable.
- Human actions now expose the exact immutable screenshot artifact ID/hash, validated browser
  session health, normalized safe loopback origin, expiry, fixed consequences, local handshake
  state, verifier state, and explicit cancellation. The API is `no-store`, and the UI downloads
  evidence only through the candidate-authorized artifact route. The interactive transport
  capability remains explicitly unavailable: no CDP/WebSocket secret, browser profile path, or
  pretend resume link is exposed. Expired actions reconcile every 15 minutes independently of the
  longer profile-retention window and return the application to auditable form filling.

## Latest verification

- Backend: `ruff format --check`, Ruff lint, strict mypy, and **303 pytest tests pass**, with one
  explicit Chromium skip and five non-failing warnings, on Python 3.14.4. Controlled-path tests
  prove disabled-by-default behavior, exact-once autonomous confirmation, pre-click policy drift,
  CAPTCHA/OTP/form/URL denial, human-action escalation, permit-before-POST ordering, explicit safe
  retry after pre-click denial, ambiguous-click no-retry behavior, and crash-after-boundary stale
  reconciliation.
- Frontend: ESLint, strict TypeScript, **72 Vitest tests**, the Next.js production build, and
  discovery of all **11 Playwright tests** pass for this checkpoint. The component suite covers
  controlled approval/queue state and the terminal unknown-outcome warning.
- Migrations: fresh SQLite upgrade, newest-revision downgrade/re-upgrade, and `alembic check`
  pass through `2a4d7e9f1b30`. The new controlled-attempt table and authorization bindings are
  present, and models and Alembic report no missing operations.
- WSL Docker verification on 2026-08-09: API, PostgreSQL, Redis, and frontend report healthy; the
  homepage and main authenticated fictional-candidate views return HTTP 200.
- CORS preflight returns HTTP 200 with the exact allowed origin for both `localhost:3000` and
  `127.0.0.1:3000`. The committed Playwright route suite still needs an actual Docker-backed run.
- The general and browser workers are running, but the scheduler exited with code 1 after a durable
  idempotency key collided with a different task payload. Full default-stack health remains unproven
  until this is repaired and exercised across repeated cycles.
- No live applications, employer contact, CAPTCHA bypass, ATS manipulation, committed credentials,
  or real candidate fixture data were introduced.

The 2026-08-06 non-Docker host audit remains the source for the complete quality-gate totals above.
On 2026-08-09, WSL Docker built the API image with Chromium dependencies and started the full stack.
A stale named candidate volume exposed an older fictional `experience.json`; the file was backed up,
replaced with the validated repository fixture, and validated from both API and worker containers.
This was persisted demo-data schema drift, not an incomplete project-spec implementation.

## Remaining definition-of-done gaps

- Acceptance criteria 2 and 3 and the pilot checks (20 generated CV comparisons, 10 real job
  posts, fact validation, and open-decision resolution) require Alessandro's private candidate
  package and human review. Repository policy forbids copying those real facts into fixtures. The
  same behavior is covered with the fully configuration-driven fictional candidate, but the named
  pilot itself must be onboarded privately outside version control.
- Acceptance criterion 22 cannot be claimed complete until a deployment supplies a secure
  interactive browser-session takeover broker. The current handshake, immutable evidence,
  same-session verifier, expiry, cancellation, and fail-closed UI are complete and truthfully label
  interactive transport unavailable; inventing or exposing a local profile/CDP secret would weaken
  the boundary.
- Acceptance criterion 23 still requires execution of the committed Playwright browser suite.
  PostgreSQL, Redis, Compose startup, local HTTP, and container health are now verified on WSL Docker.
  The image contains Chromium and its dependencies; run and repair the actual route suite next.
- The real controlled adapter must receive a security review in its deployment environment before
  its process flag and per-candidate policy are enabled. This build deliberately made no live ATS
  request or final click; doing so would violate the repository safety boundary rather than close
  an automated test gap.
- Milestone 7's provider-neutral classification, status updates, correspondence UI, and interview
  package are complete with deterministic messages. Live Gmail ingestion still requires an OAuth
  client, OS-keychain/managed-secret integration, and account authorization not present in this
  workspace. No automatic reply capability exists.

External conditions still block the named pilot and final production claims. Independent local work
remains: simplify the web pipeline, make autonomy prerequisites actionable and evidence-backed, run
the committed Playwright suite in Docker, and harden persisted candidate-volume schema handling.

## Resume instructions

1. Read `docs/AUTONOMOUS_BUILD_PLAN.md` and this file.
2. Inspect Git status and do not stage `scripts/run-autonomous-build.sh` or `artifacts/`.
3. Implement the immediate local UX/autonomy-readiness TODO before expanding production scope.
4. Run the committed Playwright suite in Docker, repair failures, and record exact evidence without
   enabling a live final click.
5. Resolve tested-adapter and dry-run blockers only from passing synthetic evidence; add the explicit
   user confirmation flow but do not confirm autonomy on the user's behalf.
6. Supply and security-review a deployment-specific interactive takeover broker before claiming the
   same-session takeover acceptance criterion.
7. Privately onboard the pilot candidate and Gmail OAuth only through approved private secret and
   data handling; never commit personal data.
