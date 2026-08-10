# Autonomous Build Plan

## Objective

Implement and verify the complete definition of done in `CareerOS_PROJECT_SPEC(1).md` from
the current repository state. Preserve the deterministic `SubmissionGate` boundary, candidate
isolation, immutable history, truthful provenance, and the prohibition on live applications,
CAPTCHA bypass, ATS manipulation, employer contact, and committed real candidate data during this
build. A production-shaped final-click path may exist only behind the specification's explicit,
default-deny controls and must be verified without sending a live application.

## Repository baseline

- Branch: `autonomous-build`.
- Milestone 1 is substantially complete: strict fictional candidate configuration, readiness,
  snapshots, candidate APIs and core UI, candidate-scoped persistence, state machine, isolated
  agent contracts/fakes, deny-by-default gate, immutable archive skeleton, and local stack shell.
- The authoritative spec's Milestones 2–8 and most full-product acceptance tests remain.
- Existing local changes in `scripts/run-autonomous-build.sh` and `artifacts/` predate this build;
  they are user-owned and excluded from implementation commits.
- The later untracked root file `how d8c72b0` is also user-owned and excluded without inspection.
- The inherited worktree contains uncommitted, passing foundations for discovery, materials,
  synthetic browser dry runs, operations, correspondence, and local-auth primitives. These are
  preserved and integrated instead of recreated.
- The current runtime is Python 3.14.4. The previously recorded FastAPI `TestClient` hang no
  longer reproduces: the complete 87-test backend suite passes.
- WSL Docker is now available. On 2026-08-09 the API image built with Chromium dependencies and the
  default Compose stack started with healthy API, PostgreSQL, Redis, and frontend services.
- Live CORS preflight and the main fictional-candidate API views are verified. The committed
  Playwright route suite still needs a full Docker-backed execution and repair pass.
- The specification contains real pilot data, but repository safety rules prohibit committing
  it. Pilot behavior will be proven with fictional configuration and documented onboarding
  blockers rather than copying personal data into version control.
- Resume audit on 2026-08-06 found an inherited, uncommitted isolated browser-worker slice. It
  adds durable task attempts, immutable evidence, bounded retry/escalation behavior, archive/gate
  binding, a dedicated Compose worker, and regression coverage. Preserve it, run the complete
  quality and migration gates, review it for tenant/safety regressions, and commit it as the next
  coherent checkpoint before starting material-policy work.

## Immediate next milestone - simple website pipeline and autonomy readiness

This milestone is the first priority for the next autonomous run. It produces a usable local first
version with `example_candidate`; it does not authorize live applications or claim the full external
pilot definition of done.

1. Map the existing web routes into one guided user journey: select or onboard a candidate, resolve
   readiness, discover/select a job, generate and review materials, run a safe dry run, resolve human
   actions, and explicitly approve a controlled action.
2. Give each stage one obvious primary action, plain-language completion state, and a direct link to
   the next unresolved prerequisite. Move technical metadata and advanced policy controls behind
   progressive disclosure without removing auditability.
3. Replace raw autonomy blocker codes with actionable cards that explain why each blocker exists,
   what evidence is present, and what safe action can resolve it.
4. Close `no_tested_ats_adapter` only through a durable passing synthetic adapter acceptance record
   bound to the adapter and form pattern; never through a blind user toggle or live submission.
5. Close `dry_run_acceptance_not_passed` only through successful candidate-scoped dry-run evidence
   and the committed browser acceptance suite.
6. Add an explicit unchecked confirmation flow after the evidence prerequisites pass. Show limits,
   emergency-stop behavior, exact scope, and consequences; audit the decision. Never confirm on
   behalf of the user.
7. Keep `approval_required` as the demo default and preserve all SubmissionGate, CAPTCHA, isolation,
   provenance, and immutable-archive boundaries.
8. Add backend, component, route, accessibility, and Docker-backed browser tests for the guided flow.
9. Add non-destructive detection and recovery guidance for persisted fictional candidate volumes
   whose schema is older than the image fixture; never delete or overwrite unknown user candidates.

Acceptance for this milestone:

- A new user can identify the next safe action without reading internal policy codes.
- The fictional pipeline can be demonstrated end to end through dry run and manual approval.
- Each autonomy blocker is either backed by exact passing evidence or remains visibly blocked.
- Docker Compose reports all default services healthy and primary demo routes load successfully.
- No live final click, employer contact, real candidate data, or fabricated readiness evidence occurs.

### 2026-08-09 execution plan

This run resumes at commit `37e0d74` with only the documented user-owned `artifacts/`,
`scripts/run-autonomous-build.sh`, and `how d8c72b0` untracked. It will not restart completed
milestones or stage those paths.

1. Repair scheduler command identity so a recurring schedule bucket has a stable payload-bound key
   and distinct scheduled operations cannot collide. Add regression coverage for repeated cycles
   and retained historical tasks.
2. Add durable, candidate-scoped synthetic adapter-acceptance evidence and derive
   `no_tested_ats_adapter` exclusively from a currently passing record bound to adapter version and
   form fingerprint.
3. Derive `dry_run_acceptance_not_passed` exclusively from immutable successful browser-attempt
   evidence for the candidate and supported form pattern.
4. Add a separate explicit, unchecked, consequence-aware autonomy confirmation command that is
   unavailable until the two evidence prerequisites pass and records the authenticated user action
   in the administrative ledger. Keep `approval_required` as the default and never exercise a live
   click.
5. Turn the existing routes into a plain-language guided pipeline with one recommended action per
   stage and advanced evidence under progressive disclosure. Cover it with backend, component,
   accessibility, and Playwright route tests.
6. Replace destructive stale-volume repair instructions with startup detection, an exact report,
   and copy-to-new-candidate or reviewed migration guidance. Never overwrite or delete an unknown
   persisted candidate package.
7. Rebuild the default Compose stack, exercise repeated scheduler cycles, and execute the committed
   Playwright suite inside the browser-capable container. Record exact current results.
8. Audit the remaining specification acceptance criteria, run every repository quality gate,
   review for secrets/real data/scope regressions, update durable status, and commit each coherent
   passing milestone.

Execution result: steps 1–8 are complete with deterministic regression coverage. The browser matrix
passes 20/20, the frontend Playwright suite passes 13/13, and the final application images run in
the seven-service Compose stack with healthy primary routes and repeated scheduler processing.
The only remaining definition-of-done
work requires external private pilot data and human review, deployment identity/encryption and
secure interactive takeover infrastructure, live-provider credentials/security review, or a
real provider environment; none may be fabricated or weakened in repository code.

### 2026-08-10 resumption audit

The run resumed at `d261afd` without restarting the completed guided-flow milestone. The tracked
tree is clean; `artifacts/`, `scripts/run-autonomous-build.sh`, and `how d8c72b0` remain preserved
user-owned untracked paths. The baseline backend format, lint, strict typing, and non-browser tests
pass; the frontend lint, strict typing, 78 Vitest tests, and production build pass.

The next coherent local hardening slice is to scope the Docker image candidate fixture copy to the
committed `example_candidate` package. Copying the whole local `candidates/` directory could embed
an untracked private candidate in `/app/candidate-fixtures`, where runtime volume masking would not
hide it. Add a static build-context regression, then rerun all quality, migration, scheduler,
volume-safety, and host browser gates.

Result: the image and build context now admit only the tracked fictional package. The website's
guided-state selection is deterministic for multiple and terminal applications, readiness/workflow
controls are editable through a versioned candidate command, allowed-adapter setup precedes synthetic
acceptance, autonomy confirmation remains unavailable while any prerequisite is blocked, and both
user approvals record versioned consequence evidence. Administrative audit rows reject database
updates. All 356 backend tests, 87 frontend unit tests, 20 backend browser cases, and 13 frontend
Playwright scenarios pass; fresh migration upgrade/check/downgrade/re-upgrade passes at
`8e4b6c1d9a20`.

Docker cannot currently be invoked from this execution environment: `/usr/bin/docker` points to
the absent `/mnt/wsl/docker-desktop/cli-tools/usr/bin/docker`. Do not retain a current healthy-stack
claim from an earlier session. If the bridge becomes available, rebuild without deleting volumes,
observe every default service across repeated scheduler cycles, inspect the mounted fictional
volume non-destructively, and run the committed Playwright suite. Otherwise record this exact
external verification limitation and continue all independent work.

Reconciled implementation decisions:

- Generic settings updates will no longer accept tested-adapter, dry-run-acceptance, or explicit
  confirmation assertions. Passing adapter acceptance will be an append-only candidate-scoped
  record bound to a synthetic browser attempt, adapter implementation version, form fingerprint,
  and immutable evidence hash. Dry-run acceptance will be derived from the same verified attempt
  evidence rather than a mutable settings flag.
- Autonomy confirmation will be a separate authenticated command. It requires an explicit checked
  acknowledgement, the current consequence-text version, and both evidence prerequisites. Its
  scope digest will include the evidence and active limits so later scope drift fails closed.
- The overview will carry the six-stage guided path. Existing detail pages remain authoritative and
  gain direct next-action links; technical evidence stays available under progressive disclosure.
- Container startup will compare the mounted fictional package with the image-bundled validated
  fixture and emit a body-free, hash-based diagnostic. Recovery will preserve the mounted package
  and guide copy/export plus reviewed migration; startup code will never replace it.

## Execution order

### Phase 1 — Milestone 2: discovery, analysis, and jobs inbox

1. Add versioned normalized job contracts and persistence without breaking Milestone 1 data.
2. Add deterministic URL/domain validation, prompt-injection scanning, description
   normalization, duplicate fingerprints, and candidate application duplicate hashes.
3. Add Greenhouse, Lever, and Ashby adapters behind an allowlisted adapter protocol. Tests use
   deterministic fixtures; no live provider access is required.
4. Add candidate-configured classification, salary checks, hard blockers, dimensional scoring,
   bonuses/penalties, evidence, and distinct per-candidate results.
5. Add candidate-aware job repositories and APIs for discovery, list/detail, verify, analyze,
   shortlist, and skip with idempotency and stable error codes.
6. Add `/jobs` inbox/detail pages, discovery status/controls, evidence, blockers, freshness,
   security findings, and score explanations. No bulk submission.
7. Add worker/scheduler process boundaries and persistent runtime volumes to Compose.

### Phase 2 — Milestone 3: materials and preview

1. Implement approved-fact selection, claim provenance, CV/cover-letter/answer generation,
   templates, deterministic rendering and validation, and independent semantic review.
2. Persist immutable draft versions and manual edits without overwriting history.
3. Add material preview, download, provenance, validation/review, and version UI.

Status: deterministic generated documents now have an integrated preview and append-only manual
revision path. A revision can only preserve the canonical target heading and select, remove, or
reorder exact approved-fact bullets from the immutable application snapshot; arbitrary prose,
forged provenance, stale bases, changed destinations, and post-approval edits fail closed. Each
revision creates new source/report/PDF versions, re-reviews the full package, records actor and
lineage metadata, and keeps prior versions immutable. Role-aware selection, full cover-letter
policy, and versioned free-text-answer editing are complete. Answer generation, manual edits, and
removed prompts append exact hash/snapshot-bound revisions; review, gate, archive, and interview
consumers resolve only the active latest revision while detail retains immutable history.

### Phase 2A — integration and tenant-safety repair

Before expanding UI surface area, close the cross-cutting gaps exposed by the baseline audit:

1. Bind every candidate-owned child record to the same candidate as its parent at the database
   boundary and add adversarial isolation regression tests.
2. Persist one-time submission authorization consumption so process restarts cannot replay a
   final submission.
3. Wire local session ownership, CSRF checks, stable idempotency, and rate limiting into the API;
   never trust a query/body `candidate_id` without matching authenticated scope.
4. Build a persistence-backed application service that integrates materials, human actions,
   security events, settings, analytics, correspondence, artifacts, and audit history.

Status: tenant constraints, durable authorization, local auth/CSRF, applications, human actions,
security, settings, analytics, artifacts, correspondence, notifications, and interview packages
are integrated.

### Phase 3 — Milestone 4: browser dry run and human action

1. Add a restricted Playwright worker and synthetic ATS fixture server.
2. Add candidate-isolated persistent sessions, field mapping, allowlisted uploads, final-page
   extraction, CAPTCHA/OTP detection, and human actions. Synthetic runs never click a real final
   submit control.
3. Add human-action APIs and queue/takeover UI with same-session resumption.

Status: the restricted Playwright harness is integrated through a dedicated durable task worker.
Enqueue and state mutation are atomic; browser activity runs outside SQL; exact lease ownership is
rechecked when immutable PNG/HTML/manifest evidence and workflow state are finalized. General and
browser workers claim disjoint task kinds. Attempt history, categorized bounded retries, profile
reuse, stale-lease recovery, human escalation, and same-session CAPTCHA/OTP handling are covered by
deterministic tests. The gate and archive verify the exact attempt manifest and bytes, and the
worker has no submit operation. The actual Chromium test is skipped on this host; the Docker path
and deployment-specific interactive transport remain external.

Hardening update: human-action views now bind the exact task/attempt/session screenshot artifact,
validate the candidate session directory before reporting browser health, expose only a normalized
loopback origin, and show verifier, expiry, continuation, and cancellation state. The UI can
download evidence by exact authenticated artifact ID and cancel explicitly. A local handshake is
reported separately from the interactive transport capability, which truthfully remains
unavailable until a deployment-specific broker exists. Fifteen-minute action expiry is reconciled
on the 15-minute scheduler cadence independently of long-term browser-profile retention.

### Phase 4 — Milestones 5 and 6: controlled submission and operations

1. Complete the required pre-submit archive and one-time, short-lived authorization consumption.
2. Implement a default-disabled controlled executor with an isolated worker, exact adapter policy,
   a durable pre-click boundary, and no automatic retry after an ambiguous click. Verify it only
   with deterministic fakes; never submit a live application during the build.
3. Add confirmation-aware application detail/pipeline, exact artifact viewers, notifications,
   rate limits, approval/autonomous modes, emergency stop, settings, dashboard, and analytics.
4. Prove the UI cannot claim success without backend confirmation and cannot enable autonomy
   while readiness is blocked.

Status: complete in local deterministic coverage. Synthetic submission remains available for the
fictional workflow. The distinct Greenhouse controlled path is default-disabled, absent from
default Compose, and claimable only by its dedicated worker. It binds an exact target, package,
authorization, browser session, form fingerprint, evidence hashes, and one-use in-memory permit;
it repopulates and rechecks the exact snapshot-derived identity/CV payload, rejects unsupported
visible controls, permits one same-origin POST, and makes every post-boundary ambiguity terminal
`UNKNOWN_AFTER_CLICK`. Approval/autonomous UI, notifications, transactional rate limits, durable
task scheduling, stale-boundary reconciliation, and administrative evidence are complete.

Hardening update: confirmation evidence is backend-owned, authorization claiming is an atomic
conditional update with durable replay, denied gate preflights do not seal orphan archives, exact
required submitted documents fail closed, and successful runs create a copy-on-write confirmed v2
archive while preserving the pre-submit v1 archive.

### Phase 5 — Milestones 7 and 8: correspondence and hardening

1. Add provider-neutral correspondence ingestion/classification with deterministic Gmail
   fixtures, status updates, correspondence UI, and interview packages. No automatic replies.
2. Add local authentication, tenant-aware authorization, encrypted secret interfaces,
   candidate export/deletion, signed artifact access, administrative audit, CSRF/session/rate
   protections, and isolated worker ownership needed before hosted deployment.

Status: correspondence persistence/classification/state integration, notifications, immutable
interview packages, local session ownership/CSRF, tenant constraints, artifact authorization,
exports, and administrative audit are complete. Rich onboarding, executable deletion/retention,
hosted encryption, and separate Playwright worker ownership remain.

### Phase 5A — candidate fact controls and portable data

1. Extend candidate packages with fact-level approval, verification, confidentiality, archive,
   and document-eligibility controls while loading older packages conservatively.
2. Add optional certification, publication, and secret-free notification-rule domains to the
   loader, snapshot, versioned editor, fictional fixture, and readiness model.
3. Derive generation inputs only from approved public facts. Internal, archived, unverified,
   expired, and non-auto-submit data must never reach outward material generation.
4. Keep onboarding drafts empty and unapproved instead of copying approved fictional evidence.
5. Add deterministic CV-import draft extraction and explicit approval workflow without storing
   or committing real candidate documents.

Status: all five steps are implemented. CV import accepts bounded TXT, page-limited PDF, and
ZIP/XML-limited DOCX input, stores only a hash and structured extraction draft, applies
education/experience atomically as restricted and unapproved facts, and blocks readiness pending
explicit review. API, CLI, profile UI, idempotency, and failure-path tests are included.

### Phase 5B — active candidate propagation

1. Persist a validated active candidate in a same-site local cookie.
2. Propagate selection through dashboard data, primary navigation, list routes, and detail routes.
3. Preserve an explicit query override while rejecting malformed candidate IDs.

Status: complete. Candidate-card navigation selects the active profile, all operational links carry
it explicitly, server pages fall back to the validated cookie, and the dashboard loads and labels
the same candidate. Frontend regression coverage proves cross-route propagation.

### Phase 5C — rendered document identity

1. Render versioned PDFs before material approval without network or dynamic template execution.
2. Validate page count, complete text extraction, supported glyphs, safe URLs, fixed non-overlapping
   layout, source hash, and output hash; persist a fail-closed report.
3. Upload only the candidate/application-scoped rendered PDF and verify its exact stored hash at
   browser and gate boundaries.
4. Copy the same rendered bytes into the immutable archive; never rerender or truncate at archive
   time.
5. Bind authorization to a digest of the reviewed versions, browser upload, candidate snapshot,
   and verified archive; reconstruct and compare that digest before authorization consumption.
6. Expose rendered drafts, template/version, page count, extraction result, and exact downloads in
   the application UI.

Status: complete for deterministic PDF output. CV template selection is versioned and allowlisted;
DOCX remains optional. Tests cover pagination without truncation, glyph/URL/template/page failures,
persisted render denial and regeneration, exact-version approval, candidate/symlink isolation,
authorization-package drift, exact browser upload hash, and byte-identical archives.

### Phase 5D — durable scheduled discovery

1. Persist candidate-owned Greenhouse, Lever, and Ashby source configuration and discovery runs.
2. Fetch only through a bounded read-only transport with exact provider URL policy, response limits,
   deterministic error categories, and injectable fixtures.
3. Enqueue enabled sources once per cadence bucket and execute them through leased worker tasks.
4. Reuse normalization, injection quarantine, versioning, deduplication, and candidate scoring.
5. Expose source freshness, counts, next run, and failures through authenticated API/UI surfaces.

Status: complete for credential-free scheduled discovery. Candidate-owned sources and run status
are durable; exact provider endpoints are fetched through bounded read-only transports; cadence
tasks use transaction-fenced leases and content-bound replay keys; every source mutation has a
payload-bound receipt; missing settings and empty adapter allowlists fail closed; safe changed jobs
alone are reanalyzed; settings and jobs surfaces expose policy and execution status. Manual payload
import is labeled development-only.

### Phase 5E — executable candidate lifecycle controls

1. Produce a bounded portable export from one repeatable database snapshot and a candidate
   lifecycle reader lease, including configuration, candidate-owned rows, referenced shared-job
   evidence, exact archives, and safe browser evidence while excluding secrets and local paths.
2. Execute intentional deletion only after exact-ID confirmation and a payload-bound command key.
   Establish a durable database tombstone and filesystem marker as one ordered operation, fence
   every candidate writer, remove raw candidate audit rows, and retain only a keyed pseudonymous
   deletion audit plus minimal stale-writer receipt.
3. Serialize file publishers, exports, discovery scheduling, workers, and deletion across
   processes; make interrupted deletion replayable through API, settings UI, and CLI status.
4. Enforce configurable browser-profile retention for confirmed, cancelled, ready, synthetic,
   and expired human-takeover sessions using rollback-safe filesystem quarantine.
5. Add deterministic race, replay, traversal, symlink, stale-writer, retention rollback, export,
   API, CLI, and frontend recovery tests.

Status: complete for the local single-user deployment. Export is descriptor-relative and
`O_NOFOLLOW`, recursively redacts path/idempotency/capability fields, includes the restricted
Playwright worker's evidence filenames, and applies count/per-file/aggregate limits. Deletion
creates its marker inside the tombstone transaction, uses a cross-process hashed lifecycle lock,
rejects external storage locators before removing rows, and can resume both marker-only crash
states and durable failed receipts. Database triggers reject stale writes to all candidate-owned
tables, including administrative audit. Daily worker tasks purge eligible browser profiles and
return expired human-action applications to an explicit retryable form-fill state. Hosted tenant
recovery authorization, encryption, and deletion-receipt retention remain later deployment work.

### Phase 5F — payload-bound mutation replay

1. Require command keys for candidate creation, section import/update, snapshots, CV extraction,
   and CV application across API, CLI, and frontend callers.
2. Journal candidate filesystem mutations as atomic pending/completed receipts outside candidate
   packages, reconcile interrupted version publication, and purge the receipts during deletion.
3. Generalize durable SQL receipts across material generation/approval, workflow start, dry-run,
   authorization, withdrawal, correspondence, interview preparation, security resolution, and
   human-session commands.
4. Retain the same frontend command key across uncertain failures and clear it only after a
   backend-confirmed response.
5. Ensure read-only settings access does not create persistence as a hidden side effect.

Status: complete. Candidate journals bind canonical payloads without storing raw command keys,
persist exact snapshot identities, stage new candidates before atomic publication, restore updates
interrupted between section and manifest publication, and are serialized by the existing
cross-process lifecycle lease. Application receipts and effects share one database transaction and
exact responses replay before current-state checks. Natural provider/CV identities reject changed
content even under fresh keys, terminal human-action intent cannot be reversed, and command keys
are bounded before persistence. Specialized job, discovery, task, deletion, and synthetic-
submission receipts remain in place. Regression tests cover exact response replay,
changed-payload conflicts, interrupted publication, UI retry keys, and side-effect-free settings
reads.

### Phase 5G — canonical submission identity and fresh-source proof

1. Persist the specification-defined candidate application duplicate hash separately from a
   stronger candidate/company/requisition-or-URL submission identity.
2. Enforce the stronger identity with a database uniqueness constraint and fail-closed gate and
   execution checks across equivalent source records.
3. Revalidate openings against bounded, allowlisted official ATS feeds immediately before
   generation, authorization, and synthetic submission.
4. Persist open, closed, and provider-error evidence independently from later mutation rollback;
   completed idempotent commands replay without refetching.
5. Surface stale and possible-duplicate states, preserve candidate-deletion writer fences through
   SQLite table rebuilds, and cover renamed, cross-source, distinct-requisition, failure, and
   replay paths deterministically.

Status: complete. Timestamp-only verification was removed. Provider evidence binds the official
payload hash, current destination, reason, and check time; closed, changed, malformed, absent, and
unreachable sources deny progress. Legacy application identities are collision-checked before
non-transactional SQLite DDL, and the migration restores deletion-fence triggers after every batch
rebuild.

### Phase 5H — safe candidate configuration portability

1. Define a bounded, strict, deterministic JSON/YAML envelope for the complete candidate source
   configuration, with schema identity, source version, candidate identity, and a canonical hash.
2. Reject duplicate keys, YAML aliases/tags, excessive depth/size, unknown fields, hash drift, and
   cross-candidate bundles before creating any mutation receipt or history.
3. Import all candidate sections under one lifecycle lock and one profile-version publication,
   with optimistic versioning, payload-bound replay, rollback history, and no-op detection.
4. Preserve local file layout and operational workflow/active switches so a portable bundle cannot
   silently enable automation. Never import SQL workflow rows, archives, browser profiles,
   credentials, receipts, or deletion state through this configuration path.
5. Expose distinct API, CLI, and settings controls for configuration JSON/YAML portability while
   retaining the existing bounded lifecycle export as a separate backup/audit artifact.

Status: complete. Both formats round-trip deterministically, the codec and transport are bounded,
and the backend publishes a changed whole configuration as exactly one new version. Exact command
replays return the original result; stale versions and changed payloads fail closed. The settings
surface labels configuration transfer separately from the full lifecycle export and retains an
import command key across uncertain failures.

### Phase 6 — definition-of-done verification

1. Audit all 24 acceptance criteria and mandatory zero-tolerance safety targets.
2. Verify Alembic upgrade/check, backend format/lint/type/tests, frontend lint/type/tests/build,
   integration/security/browser/accessibility tests, fictional local workflow, and Compose when
   Docker is available.
3. Review the complete diff for regression, secrets, generated files, personal data, and scope.
4. Update architecture, setup, operations, onboarding, security, adapter, and status documents.
5. Commit only coherent passing milestones with Conventional Commit subjects and finish with a
   clean working tree apart from preserved pre-existing user changes.

Status: all recorded backend, migration, frontend, security, and deterministic controlled
submission gates pass. PostgreSQL/Redis/Compose startup and primary HTTP routes are verified on WSL
Docker. The committed Playwright browser suite still requires an actual Docker-backed execution and
repair pass. A deployment-specific secure interactive takeover broker is also required before the
corresponding acceptance criterion can be claimed complete.

### Current execution checkpoint

1. [Complete in `b1824cc`] Validate and integrate the inherited browser-worker attempt-evidence
   slice after backend, frontend, migration, and security gates pass.
2. [Complete in `5243624`, `f1084d2`, and the pending normalized-schema commit] Broaden the
   normalized job contract to the specification fields and route runtime job analysis through a
   provider-neutral, strictly typed `JobAnalysisAgent` boundary with a deterministic local
   provider.
3. [Complete] Implement the remaining Milestone 3 policy surface as small end-to-end slices:
   role-specific template/content selection, configuration-driven cover-letter inclusion, and
   append-only free-text answer revision with backend-derived provenance and review.
4. [Complete] Add the browser route/accessibility-critical test layer using deterministic local
   fixtures. Isolated Chromium and extracted system libraries run the 20-test backend browser
   matrix and the 13-test committed frontend suite without changing the host system.
5. [Complete] Add a fail-closed exact submitted-package viewer that distinctly identifies the
   immutable submitted CV, cover letter, answers, and final receipt and downloads/previews by exact
   backend artifact ID without rendering HTML.
6. [Complete for local evidence; transport external] Expand the human-action evidence and expiry
   contract without exposing browser profile paths, CDP/WebSocket secrets, or claiming that a
   database handshake is an interactive takeover capability.
7. [Complete in deterministic local coverage] Add the default-disabled controlled-submission
   adapter, one-use gate permit, durable irreversible-click evidence, no-retry unknown outcome,
   approval/autonomous queueing, exact confirmation archive, API/UI, migration, and regression
   tests without making a live submission.
8. [Complete] Execute and repair both committed browser suites with all provider requests
   intercepted, then rebuild and health-check the seven-service Compose stack.
9. [Complete] Implement the simple guided website pipeline and evidence-backed autonomy blocker
   actions defined in the immediate milestone.
10. [External] Supply and review the deployment-specific secure interactive takeover transport.

Runtime agent routing and the normalized job expansion are complete. The deterministic provider
receives a minimal scoring-only candidate context, all identities are lifecycle/content/version
bound, and final scoring/blockers remain an independent deterministic service decision. Section
9.3 fields now survive strict adapter normalization, append-only versions, database persistence,
scoring, API serialization, and job-detail presentation. Missing provider facts stay null; the
first rediscovery under this normalization envelope may create one intentional new version.

## Conservative decisions

- External HTML and job text always remain untrusted data; adapters only extract structured
  fields and cannot invoke tools or alter policy.
- Missing or ambiguous values fail closed and create blockers or human actions.
- All network-facing provider behavior is exercised through deterministic fixtures unless a
  read-only provider call is explicitly safe and necessary.
- Backend validation and state are authoritative; the frontend never duplicates submission
  authorization logic or optimistically reports success.
- Major schema/API changes are migration-backed and backward-compatible where practical.
- Missing optional candidate files load as unconfigured domains. Missing approval metadata always
  defaults to false; compatibility never silently upgrades a legacy fact to approved.
- The specification's named pilot data is not copied into version control because the repository
  instructions explicitly prohibit real candidate data. Pilot readiness is represented as an
  onboarding/configuration task and all executable acceptance paths use fictional `.invalid`
  identities.

## Quality gates per coherent slice

```text
ruff format --check app tests migrations
ruff check app tests migrations
mypy app tests
pytest
alembic upgrade head
alembic check
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

Relevant focused tests run first after each edit; the full set runs before every milestone commit.
