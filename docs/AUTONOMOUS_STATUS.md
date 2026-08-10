# Autonomous Build Status

## Current state

- Build status: **ALL LOCALLY IMPLEMENTABLE DEFINITION-OF-DONE WORK VERIFIED**
- Active phase: final review/commit; remaining acceptance work requires external private data,
  provider credentials/security review, hosted infrastructure, or a secure takeover transport
- Branch baseline: `autonomous-build` at `d261afd`; the guided workflow checkpoint is published
  through `3fa4aff` and later local security/runtime hardening is included through `d261afd`.
- Current local milestone commits: `c0bf6e9` (durable autonomy/scheduler/browser/volume safety) and
  `5257f2d` (guided web workflow and durable verification documentation).
- Authoritative specification: `CareerOS_PROJECT_SPEC(1).md` version 1.1.0
- Preserved pre-existing workspace items: `scripts/run-autonomous-build.sh`, `artifacts/`, and the
  untracked root file `how d8c72b0`; these are not staged.
- Current autonomous run began on 2026-08-09 at `37e0d74`. The full specification and applicable
  architecture, implementation, milestone, operations, security, onboarding, adapter, plan, and
  status documents were reread before implementation.
- The immediate local milestone is complete: scheduler identity is payload-stable, autonomy
  prerequisites are durable evidence rather than mutable assertions, the user-only confirmation is
  separately audited, the six-stage website path exposes one next action, stale fictional volumes
  are detected without mutation, and both committed browser suites pass on the host. Manual approval
  remains the default and controlled live execution remains disabled.
- Current 2026-08-10 resumption evidence: Ruff format/lint and strict mypy pass; all **360** backend
  tests pass with the isolated Chromium runtime, including **20/20** browser cases. Frontend
  lint/typecheck, all **87** Vitest tests, the production build, and the separate **13/13**
  Playwright route/safety/accessibility suite pass.
- Current Docker evidence is blocked: `docker` is not callable because `/usr/bin/docker` points to
  an absent `/mnt/wsl/docker-desktop/cli-tools/usr/bin/docker`. Earlier healthy-service and mounted-
  volume observations below are dated evidence, not a current health result.
- The Docker build-context privacy gap is closed: the image copies only the committed fictional
  `example_candidate`, and `.dockerignore` rejects every other candidate package and private
  runtime directory. A deterministic regression checks both boundaries.
- The website now edits readiness approvals and workflow switches through a payload-idempotent,
  versioned candidate command. Automatic submission still requires a separate unchecked,
  consequence-aware acknowledgement and does not confirm autonomy or authorize a final click.
- Administrative audit rows are now database-immutable on SQLite and PostgreSQL; candidate erasure
  may still delete them under the existing lifecycle policy. Manual controlled approval records a
  versioned consequence statement and actor in the immutable application event.
- Operational logs now use a bounded JSON field allowlist and request correlation IDs without
  bodies, tokens, candidate facts, or hidden prompts. Committed CI repeats strict backend,
  migration, frontend, production-build, and both Chromium suites. Append-only ADRs record the
  deterministic submission and candidate-isolation decisions.

## Completed local milestone - first-version UX and autonomy readiness

- [x] Simplify the normal website journey into one guided pipeline: candidate readiness, job selection,
  material generation/review, safe dry run, human-action resolution, and explicit controlled approval.
  Each page should expose one primary next action and link directly to the blocker it can resolve.
- [x] Use progressive disclosure: show plain-language status, consequences, and next actions by default;
  keep hashes, internal IDs, raw policy fields, and advanced controls in expandable detail.
- [x] Replace raw autonomy blocker identifiers with user-facing explanations, current evidence, and a
  concrete action. Preserve backend authority and fail-closed behavior.
- [x] Resolve `no_tested_ats_adapter` only from a recorded passing synthetic acceptance run for the exact
  adapter/form pattern. Do not provide a manual checkbox that can claim untested evidence.
- [x] Resolve `dry_run_acceptance_not_passed` only from candidate-scoped passing dry-run evidence and the
  committed browser acceptance suite. Do not let the user self-declare the test passed.
- [x] Add an explicit, unchecked autonomy confirmation step only after all evidence prerequisites pass.
  Explain scope, rate limits, emergency stop, and consequences; persist an administrative audit event.
  The agent must not confirm autonomy on the user's behalf.
- [x] Keep `approval_required` as the first-version default and keep live controlled submission disabled at
  the process boundary during development and automated verification.
- [x] Add component, route, accessibility, and backend tests for the guided path and every blocker action.
- [x] Repair the scheduler's durable task idempotency collision
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
- Candidate onboarding now includes bounded local TXT, PDF, and DOCX CV extraction through API,
  CLI, and the profile UI. PDF page counts and DOCX ZIP/XML expansion are strictly bounded. Raw
  documents are not retained; deterministic education/experience drafts carry the source hash,
  restricted confidentiality, and false approvals. Applying a draft creates one version atomically
  and blocks readiness until explicit review.
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
- The frontend has host-runnable axe checks plus a 13-test Chromium route/safety/accessibility suite
  with deterministic API interception and fictional fixtures. Isolated browser libraries allow the
  suite to execute on the minimal host without mutating system packages.
- Human actions now expose the exact immutable screenshot artifact ID/hash, validated browser
  session health, normalized safe loopback origin, expiry, fixed consequences, local handshake
  state, verifier state, and explicit cancellation. The API is `no-store`, and the UI downloads
  evidence only through the candidate-authorized artifact route. The interactive transport
  capability remains explicitly unavailable: no CDP/WebSocket secret, browser profile path, or
  pretend resume link is exposed. Expired actions reconcile every 15 minutes independently of the
  longer profile-retention window and return the application to auditable form filling.

## Latest verification

- Backend: `ruff format --check`, Ruff lint, strict mypy, and **360 pytest tests pass** with seven
  non-failing dependency deprecation warnings on Python 3.14.4. With isolated Chromium and extracted
  libraries, the real synthetic browser matrix passes **20/20** across standard, optional-cover,
  multi-step, changed-label, closed-job, timeout, retry, and fail-closed novel-field cases.
- Frontend: ESLint, strict TypeScript, **87 Vitest tests**, and the Next.js production build pass.
  The committed Chromium route/safety/accessibility suite passes **13/13** with deterministic API
  interception and no provider traffic.
- Migrations: fresh SQLite upgrade, `alembic check`, newest-revision downgrade, and re-upgrade pass
  through `8e4b6c1d9a20`. Models and Alembic report no missing operations.
- Scheduler: the profile-version-bound readiness key and retained-task regressions pass in the full
  suite. The earlier rebuilt Compose cycles ran without the historical idempotency crash; current
  Compose execution is unavailable because the WSL Docker CLI target is absent.
- Candidate volume safety: the mounted fictional candidate currently differs from the immutable
  fixture and is preserved with `mutation_performed=false`. Traversal, symlink, excluded-directory,
  nested-destination, stale, and occupied-destination cases pass deterministic tests.
- Archive recovery now rejects raw-job-source or agent/model/prompt provenance drift. Injected
  material agents must declare immutable provenance, and PDF import rejects active content,
  excessive compressed streams, objects, and decompressed content before accepting extraction.
- Docker/Compose: the final application images were rebuilt earlier on 2026-08-10 without deleting
  volumes, when all seven services ran and primary health/routes returned HTTP 200. This is dated
  evidence only. In the current environment `/usr/bin/docker` is a dangling link to the absent
  Docker Desktop WSL CLI, so no current Compose health claim is made.
- No live applications, employer contact, CAPTCHA bypass, ATS manipulation, committed credentials,
  or real candidate fixture data were introduced.

All totals above were executed during the 2026-08-09 to 2026-08-10 run. The earlier manual stale-fixture
procedure is superseded: backend containers compare the mounted fictional candidate to an immutable
image fixture and report hashes/changed paths without mutation. A review copy can be staged only at
an absent destination, and Docker onboarding uses the immutable fixture rather than the mount.

## Acceptance-criteria audit

| Spec criterion | Result | Current evidence or blocker |
| --- | --- | --- |
| 1 | Pass | Fictional candidates onboard through API, CLI, and web as unapproved drafts. |
| 2–3 | External blocker | Alessandro's private profile and AI/ML strategy are not available and cannot be committed. |
| 4 | Pass | Candidate-scoped scoring produces different results from different configurations. |
| 5–6 | Pass | Agent contracts have no submit authority; missing facts make `SubmissionGate` deny. |
| 7 | Pass locally | CAPTCHA/OTP creates a human action and is never bypassed. Secure interactive transport is separately blocked under criterion 22. |
| 8–11 | Pass | Confirmed synthetic submissions have immutable exact artifacts, provenance, and target validation. |
| 12–15 | Pass | Duplicate identity, candidate isolation, prompt quarantine, and per-candidate disable controls are deterministic and tested. |
| 16 | Pass locally | Manual approval is the default; autonomy is scoped per tested ATS evidence and user confirmation. No user confirmation was fabricated. |
| 17 | Pass locally, current recheck blocked | A dated one-command Compose rebuild ran all seven services without touching volumes. Current recheck is blocked by the absent Docker Desktop WSL CLI target. |
| 18–21 | Pass | All routine web routes exist; success/readiness stay backend-owned; exact submitted artifacts are available by ID. |
| 22 | External blocker | Evidence, expiry, handshake, and browser-owned verification exist, but no deployment-specific secure interactive takeover broker is supplied. |
| 23 | Pass locally | Backend, frontend, browser, accessibility, security, migration, and fresh Compose integration gates pass. |
| 24 | Pass | Committed candidate data and test identities are fictional; no real candidate data was added. |

All mandatory zero-tolerance targets remain zero in deterministic coverage. No live submission was
attempted, so this run does not claim a production observation against a real ATS.

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
- The real controlled adapter must receive a security review in its deployment environment before
  its process flag and per-candidate policy are enabled. This build deliberately made no live ATS
  request or final click; doing so would violate the repository safety boundary rather than close
  an automated test gap.
- Milestone 7's provider-neutral classification, status updates, correspondence UI, and interview
  package are complete with deterministic messages. Live Gmail ingestion still requires an OAuth
  client, OS-keychain/managed-secret integration, and account authorization not present in this
  workspace. No automatic reply capability exists.

External conditions block the private-pilot, live-provider, secure-takeover, hosted-deployment, and
current Compose recheck items. The local guided pipeline, evidence-backed autonomy path, committed
browser suites, scheduler repair, build-context privacy, non-destructive candidate-volume handling,
observability, CI, and architecture decision records are complete and verified. No further useful
implementation can close those external requirements without new authority, private data,
credentials, or infrastructure.

## Resume instructions

1. Read `docs/AUTONOMOUS_BUILD_PLAN.md` and this file.
2. Inspect Git status and do not stage `scripts/run-autonomous-build.sh` or `artifacts/`.
3. Treat Docker health as dated evidence until the WSL CLI target returns; retain the passing
   Playwright evidence and do not enable a live final click.
4. Resolve tested-adapter and dry-run blockers only from passing synthetic evidence; never confirm
   autonomy on the user's behalf.
5. Supply and security-review a deployment-specific interactive takeover broker before claiming the
   same-session takeover acceptance criterion.
6. Privately onboard the pilot candidate and Gmail OAuth only through approved private secret and
   data handling; never commit personal data.
