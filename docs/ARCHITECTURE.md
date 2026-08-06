# Architecture

## Status and scope

This repository was empty when Milestone 1 began. `CareerOS_PROJECT_SPEC(1).md` became available during final verification and is treated as the product source of truth, with the current task instructions taking precedence where they intentionally narrow scope. In particular, this milestone contains only fictional candidate data and does not create the real pilot profile described in the master specification.

The current implementation integrates configuration, persistence, discovery, scoring, materials,
synthetic form filling, human actions, gate authorization, immutable archives, application history,
security/settings, analytics, and local authentication. It deliberately excludes live
applications, CAPTCHA bypass, anti-bot workarounds, and ATS manipulation. Real pilot data is not
committed; it must be onboarded privately and remains blocked until approved.

## Current integrated surface

The Next.js control plane exposes the dashboard, candidate onboarding/editor/readiness, job inbox
and analysis, application pipeline/detail, human actions, security ledger, automation settings,
and analytics. Its authenticated API client never reads local candidate or artifact paths.
Candidate selection is a validated local same-site cookie with an explicit query override; primary
navigation and server-rendered list/detail routes propagate the same candidate ID. The cookie is a
UX preference only—the backend bearer-session candidate scope remains authoritative.

The application service persists candidate snapshots, generated evidence-backed materials,
independent review, synthetic browser sessions, screenshots, state transitions, one-time gate
authorizations, and backend-confirmed outcomes. Composite foreign keys enforce that application
children and scores belong to the same candidate. Discovery commands and workflow transitions use
durable idempotency receipts.

## Safety boundary

The production application is a single deployable service which orchestrates three isolated LLM workers:

1. `JobAnalysisAgent` evaluates a job against a supplied candidate snapshot and scoring policy.
2. `DocumentGenerationAgent` creates document and answer proposals from explicit evidence.
3. `IndependentReviewAgent` independently checks semantic support, policy compliance, and completeness.

Each worker receives a complete, immutable request and returns a validated response. Workers do not share conversation history or mutable memory. Real model adapters will be process- or service-isolated in a later milestone; Milestone 1 provides strict protocols and stateless deterministic fakes.

The `ApplicationOrchestrator` controls sequencing, but cannot authorize submission. Only
`SubmissionGate` can issue a `SubmissionAuthorization`. The gate is deterministic, defaults to
denial, and treats every absent, unknown, or false prerequisite as failure. The isolated browser
worker performs only a pre-submit dry run: it never receives an authorization, scores suitability,
invents answers, generates documents, or bypasses CAPTCHA/anti-bot controls.

```text
Candidate files + global job
           |
           v
 ApplicationOrchestrator
   |          |          |
   v          v          v
 Job       Document   Independent
 Analysis  Generation Review
   \          |          /
    \         v         /
     +--> browser dry-run worker --> immutable attempt evidence
     |                                  |
     +------------- SubmissionGate <----+
                       |
                       v
                authorization or denial
```

## Candidate configuration

All candidate-specific facts and policy live under `candidates/{candidate_id}/`. The engine contains no real candidate facts or candidate-specific defaults. Each candidate directory has a `profile.yaml` with a schema version and references to these required documents:

- identity
- biography
- education
- experience
- projects
- skills
- languages
- career strategy
- scoring rules
- preferences
- legal status
- approved answers
- CV rules
- cover-letter rules
- target and blocked companies
- target and blocked roles

The loader rejects path traversal, missing required files, candidate-ID mismatches, malformed dates,
duplicate stable IDs, and internally contradictory target/block lists. Optional certifications,
publications, and notification rules may be absent and then report as unconfigured. Pydantic v2
models are strict and forbid unknown fields. Approval-related compatibility defaults are always
false, so an older package is never silently trusted.

Candidate facts carry approval and outward-use controls. Experiences and projects add archive,
confidentiality, and per-document eligibility; individual generated claims additionally require a
stable ID, verification, public usability, public confidentiality, and approval. Approved answers
carry sensitivity, validity dates, and explicit auto-submit permission. `ApplicationService`
derives the material generator's input from these controls; the generator never receives withheld
internal or unapproved text. Readiness checks minimum approved evidence, identity/biography/skills/
strategy/preferences/legal/document approvals, availability, legal verification, sensitive answers,
and unverified approved claims.

Generated text and the uploadable file are separate, linked records. A versioned, allowlisted,
network-free PDF renderer runs before independent approval and rejects unsupported glyphs, unsafe
URLs, extraction loss, unbreakable layout, and page-limit violations. Its report records source,
PDF, template, candidate-snapshot, page, extraction, and layout identities in candidate-scoped
artifact metadata. Only a hash-verified rendered PDF can enter the synthetic browser boundary.

Candidate snapshots are serialized deterministically, include the profile version and source-file hashes, and carry a SHA-256 of their canonical content for audit archives. Only fictional example data is committed.

The candidate API lists profiles, returns structured configuration, validates readiness,
creates snapshots, and updates approved core sections. Updates use the same strict models
as file loading, increment the manifest patch version, and preserve the prior source set
under `.history/{profile_version}/`.

## Web control plane

The Next.js/React/TypeScript frontend is a typed API client; it never reads candidate files
or persistence directly. It provides the overview, candidate selector, structured core
profile editor, and readiness report. Readiness is shown per domain and capability rather
than as an aggregate percentage. Blockers link to editable fields, while legal and
submission controls remain visibly fail-closed.

## Persistence

SQLAlchemy 2 declarative models represent:

- global jobs (candidate-neutral)
- candidate job scores
- applications
- application documents
- application answers
- application events
- security events
- browser sessions
- human actions
- interviews
- offers

Every candidate-specific table has a non-null, indexed `candidate_id`. Relationships and uniqueness constraints include `candidate_id` where cross-candidate ambiguity could otherwise occur. PostgreSQL is the production database; tests may use SQLite through the same SQLAlchemy model layer. Alembic owns schema evolution.

## Workflow

Applications use an explicit enum-backed state machine. Transitions are allow-listed. Invalid transitions raise a typed error. Transition commands require an idempotency key; replaying the same key with the same transition is a no-op, while reusing it for different input is an error. Retryable failures can return to their prior processing stage; terminal failures cannot transition.

State changes are recorded as candidate-scoped application events. Application commands also use
candidate-scoped administrative receipts that hash the operation, canonical payload, and command
key and retain the exact response. A cross-process candidate lifecycle lease serializes receipt
creation with the state transition. Candidate configuration mutations use a private atomic
pending/completed filesystem journal because their files must be published before a completed
receipt can be recorded; interrupted updates reconcile the expected source and target profile
versions before completing a replay.

## Submission decision

`SubmissionGate.evaluate()` consumes a frozen input containing all prerequisites and emits either:

- a denial with stable reason codes and no authorization; or
- an authorization issued by the gate with application/candidate binding and an expiry time.

Required conditions include completed configuration validation, candidate threshold satisfaction, approved legal status, complete supported answers, valid documents, successful independent semantic review, a submittable workflow state, and absence of unresolved security or human-review blocks. Missing values fail closed.

## Audit archive

The archive builder writes the specification hierarchy under candidate/year/company/job. It stores
the candidate snapshot, raw/extracted/normalized job evidence, scoring, exact PDF bytes for the
synthetic submitted documents, final answers, pre-submit/final-page captures, receipt, and JSONL
audit ledgers. The manifest hashes every file. Creation is exclusive; recursive verification
detects additions, deletions, or modifications.
The builder copies the already validated and browser-allowlisted PDF bytes rather than rendering
again, so reviewed, uploaded, archived, and downloadable document hashes are identical.
Submission authorization persists a digest over those exact document versions, the candidate
snapshot, the browser-observed upload hash, and the verified archive manifest. Submission rebuilds
that digest transactionally and fails closed before consuming a stale or mutated authorization.

### Controlled final-click boundary

The production-shaped Greenhouse click path is separate from synthetic submission and from the
restricted dry-run worker. `controlled_submission_attempts` binds one application, one
authorization, one browser session, one task, the exact target and package, and immutable pre-click
evidence. The task has one claim and only the `controlled-submission-worker` role can claim its
kind. That role is absent from default Compose and refuses to start unless the process switch is
explicitly enabled.

Preparation may inspect, screenshot, and snapshot the exact allowlisted Greenhouse form but cannot
send a POST. Because ordinary DOM form values do not survive a closed browser context, the executor
repopulates first name, last name, email, and the exact hash-verified reviewed CV from the immutable
candidate snapshot/package. It rejects every other non-hidden input, select, or textarea, hashes the
exact form payload, and verifies the populated values again at click time. Immediately before click,
the service rechecks the task lease, candidate policy,
emergency stop, rate limits, fresh source, duplicate identity, current package, browser session,
form fingerprint, and authorization binding. One transaction conditionally consumes the
authorization, records the evidence hashes and nonce hash, and transitions to `SUBMITTING`. Only
then can `SubmissionGate` turn that committed proof plus the in-memory nonce into a short-lived,
single-use `FinalClickPermit`.

The executor keeps the network POST allowance closed until the adapter has consumed that permit.
CAPTCHA, OTP, and unsupported controls stop before authorization consumption, pause the browser
session, and create a human action. A denied pre-click attempt stays in history; a later explicit
approval may create a new attempt, while the scheduler never retries one automatically. A partial
database uniqueness constraint permits only one non-denied attempt for an application.

The adapter consumes that permit and dispatches one same-origin form POST. Confirmation creates a
copy-on-write archive containing the exact final screenshot and HTML. Any ambiguity after the
committed boundary transitions to `UNKNOWN_AFTER_CLICK`; this state cannot return to a retryable or
submitting state. A stale-boundary reconciler waits beyond permit expiry, records an immutable
unknown-outcome receipt, opens a human action, and terminates the task without clicking. Autonomous
mode uses the same gate and queue path and only scans candidates with every readiness blocker
cleared.

## Deployment foundation

The backend targets Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, and
PostgreSQL. Redis provides the future durable-work coordination boundary and is currently
health-checked. Docker Compose starts PostgreSQL, Redis, the API, and the standalone
Next.js frontend with health-ordered dependencies. The API applies Alembic migrations
before serving. Backend and frontend quality gates run independently.

## Discovery and job analysis

External ATS payloads enter through strict platform adapters and are normalized before they
reach persistence or candidate logic. Adapter URLs must use HTTPS and match the exact official
ATS domain (or a subdomain); credentials, fragments, cross-domain application links, and malformed
authorities fail closed. Description text is treated as untrusted and scanned for instruction
override, secret-exfiltration, safety-bypass, local-file, and hidden-ATS-content signals.

Candidate-owned source records schedule exact public Greenhouse, Lever, or Ashby board endpoints.
The read-only transport does not follow redirects and bounds timeout, response bytes, JSON media
type, and job count. Cadence-bucket tasks are leased through the SQL queue; run status, counts,
freshness, and body-free error codes are durable. Replays reuse discovery receipts, and only changed
safe jobs are rescored.

`global_jobs` stores the current candidate-neutral normalized view. `job_versions` is append-only
and records every content change by canonical payload hash, while repeated unchanged discovery is
idempotent. Candidate evaluation is stored separately in `candidate_job_scores`, allowing the same
global job to receive different classifications, scores, evidence, blockers, and proposed actions
for different candidate configurations. Candidate thresholds and weights remain configuration,
not engine constants.

Runtime analysis crosses the `JobAnalysisAgent` protocol through a stateless
`DeterministicJobAnalysisAgent`. The request contains a strict least-privilege scoring context—not
identity, contact, legal, approved-answer, document, or secret data—and is bound to candidate
profile, job version, job payload, scoring policy, and canonical snapshot hashes. Response
correlation, dimensions, weights, totals, and threshold consistency fail closed. The service
independently recomputes authoritative classification, hard blockers, score, and proposed action;
agent output is bounded explanatory metadata and cannot relax policy or authorize submission.

Candidate inbox state is isolated in `candidate_job_decisions`. Every analyze, verify, shortlist,
or skip mutation records a durable `candidate_job_commands` receipt keyed by candidate and caller
idempotency key; discovery has its own durable receipt. Reuse with different input fails with a
stable conflict. Scheduled source creation and updates are also payload-bound and replay from
durable receipts. Missing settings or an empty adapter allowlist deny scheduling and execution.
Each job mutation locks and verifies the discovery-run attempt in its own transaction, so an
expired worker cannot commit after a newer lease owns the run. Queue completion and failure also
treat ownership loss as a non-mutating outcome, leaving the newer worker lease intact. Injection
findings block analysis and enter the candidate security ledger.

A manual `verify` command and every generation, authorization, and synthetic-submission boundary
refetch the exact allowlisted provider feed. The verifier matches the external or requisition ID,
reparses the official payload, rejects a changed application destination, and persists bounded
open/closed/error evidence before the protected mutation begins. A stored timestamp alone is never
freshness proof. Candidate applications keep the specification duplicate hash for audit and a
separate, database-unique submission identity for cross-source race prevention. Missing identity
or fresh evidence fails closed at the gate and immediately before authorization consumption.

Worker and scheduler are distinct Compose processes that advertise health through Redis, and
external ports bind to localhost by default.

## Trust and privacy decisions

Candidate CV import is a local, deterministic staging boundary. It accepts bounded UTF-8
text, extracts only explicitly structured education and experience rows, records a source hash, and
discards the raw bytes. Draft files are mode `0600`; imported facts are restricted, unverified, and
unapproved. Applying a draft merges stable IDs into both candidate sections under one profile
version and one history snapshot. Readiness treats any active unapproved imported record as a
blocker, so extraction cannot silently authorize outward use.
PDF input is rejected until a resource-isolated parser worker is available.

Generated document revision is append-only and snapshot-bound. The client supplies a base document
identity/version and edited canonical content, but the service reconstructs the approved fact
allowlist from the exact candidate snapshot referenced by the base render report. Only the original
heading and exact approved-fact bullets may remain; provenance, actor, target identity, hashes, and
render metadata are server-derived. The service validates the base report and every unchanged peer
render, appends source/report/PDF versions, re-runs independent review on the full package, and
keeps every superseded document immutable. Approval and later package binding therefore consume
the latest reviewed versions without rewriting application history.

Application-answer revision follows the same boundary but retains logical-question lineage in the
database. Every generation, manual edit, or prompt withdrawal appends a row with a monotonically
increasing version, exact content hash, actor, predecessor, reason, and candidate-snapshot
identity. Composite self-references prevent lineage from crossing a candidate, application, or
question; database triggers reject updates and deletes outside deliberate candidate erasure.
Review records bind the exact active
answer IDs, versions, hashes, and snapshot IDs. All gate, archive, and interview preparation reads
select the latest revision per question after resolving withdrawals, while application detail
exposes the complete immutable history. User text receives approved-answer provenance only when it
exactly matches the same snapshot-approved question key; otherwise support is cleared and
independent review fails closed.

## Candidate lifecycle and erasure

Portable export holds the candidate lifecycle reader lease and reads candidate-owned SQL rows from
one snapshot. It includes referenced candidate-neutral job evidence, configuration, exact immutable
archives, working artifacts, and an explicit allowlist of browser screenshots/snapshots/metadata.
Every filesystem read walks from an opened directory descriptor with `O_NOFOLLOW`, rejects
non-regular or multiply linked files, checks file identity before and after reading, and enforces
file-count, per-file, and aggregate byte limits. Recursive sanitization removes local paths,
storage locators, idempotency keys, authorization capabilities, and persistent-profile locations.

Intentional deletion runs under a hashed cross-process lifecycle lock. It validates exact
confirmation and the payload-bound command key, then creates the hidden marker inside the database
tombstone transaction. A crash before database commit leaves a marker-only state that remains
writer-fenced and is recoverable; a committed tombstone therefore always follows a durable marker.
The operation preflights every known storage locator before deleting candidate-owned rows,
configurations, runtime profiles, and archives. Database triggers reject inserts and updates under
any tombstoned candidate, including stale workflow and administrative-audit transactions.
Completed operations retain only the minimal tombstone and keyed pseudonymous deletion audit. The
raw candidate identifier in the tombstone is currently required for stale-writer rejection; hosted
deployment must define its legal retention or replace it with a tenant-safe keyed subject.

Browser-profile retention uses candidate-configured days and 15-minute leased tasks. Eligible
terminal sessions and expired human-takeover sessions move to a same-root quarantine before the metadata
transaction. Transaction failure restores the live directory; committed quarantine is finalized
idempotently on the current or a later sweep. Action expiry is reconciled as soon as a sweep sees
the 15-minute deadline, independently of whether the profile has reached its longer retention age.
An expired human action is cancelled and its application returns to `FORM_FILLING` through a
durable event, allowing a fresh safe dry run.
Immutable submitted archives are outside this sweep.

## Materials and synthetic browser dry runs

The materials boundary consumes explicit approved facts and exact approved-answer keys. Every
generated claim carries evidence IDs; hashes, target-company validation, structural PDF validation,
and independent review fail closed before a draft version can progress. Source text remains
versioned for provenance while the rendered PDF and its report are separate downloadable artifacts.
Draft storage uses candidate and application path segments, exclusive version creation, and
content-hash verification.

The browser dry-run boundary accepts a finalized structured package, maps only known synthetic
fields, validates uploads against candidate-owned paths and allowlisted SHA-256 hashes, re-reads
filled values from the DOM, and extracts the final page without a submit operation. The separate
Playwright fixture harness is hard-limited to an exact allowlisted loopback URL and stores each
candidate/session in a symlink-checked persistent browser profile. Each run permits one GET document
request; all subresources, later navigation, redirects, WebSockets, and form submissions are
blocked and counted. The worker only detects the final-submit control and has no click operation.

Dry runs are durable `browser_dry_run` tasks claimed only by the dedicated browser-worker process.
Enqueueing and the application event occur in one database transaction; navigation and rendering
run outside that transaction; finalization rechecks the exact task lease before committing workflow
state and queue completion together. Expired leases cannot commit after a newer attempt owns the
task. Failures use bounded categories and retry flags, retain safe attempt history, and escalate
non-retryable or exhausted work to a visible human action and notification.

Every attempt publishes an exclusive evidence directory containing the exact PNG, final-page HTML,
and strict manifest. The manifest binds the task attempt, candidate, application, browser session,
exact loopback URL, mapped fields, upload hashes, network counts, profile reuse, and an explicit
`submit_clicked=false`. The gate and archive re-read and hash-check those files; missing, changed,
cross-session, symlinked, or mismatched evidence denies authorization. CAPTCHA and OTP attempts keep
the same persistent profile and create a same-session human action. Completion cannot bypass the
browser-owned verifier, and only the evidence-backed final-validation event can progress.
The worker holds the candidate lifecycle fence across browser I/O and evidence publication so
intentional deletion cannot race and recreate private files. Evidence sources are read by exact
session-relative names with `O_NOFOLLOW`; stale-lease publications are discarded, and the bounded
candidate lifecycle export includes the immutable attempt-evidence tree.

Human-action presentation resolves screenshots by the exact task, attempt, and browser session
recorded in the action evidence. It reports browser health only after validating the candidate and
application binding plus the expected non-symlinked session directory, and reduces the observed
page to an allowlisted origin. Raw runtime paths never cross the API. Opening records an
authenticated, idempotent local handshake; it is not an interactive transport capability. That
capability remains unavailable until a deployment provides a server-side broker with one-time
candidate/action/session-bound grants. Completion remains separately gated by the browser-owned
same-session verifier and opening the handshake never counts as verification.

## Candidate configuration portability

Configuration transfer is deliberately separate from the lifecycle export. The portable JSON/YAML
envelope contains only the strict candidate manifest and section models, identifies its schema,
candidate, and source profile version, and binds the canonical configuration bytes with SHA-256.
Parsing rejects duplicate keys, aliases, custom YAML tags, unbounded structures, unknown fields,
hash drift, and candidate mismatch before mutation begins.

Import holds the same cross-process candidate lifecycle lock used by editing and deletion. It
normalizes the source onto the destination's candidate identity and file layout, preserves local
`active` and workflow switches, validates the complete model, and publishes all changed sections
with one patch-version increment and one rollback history snapshot. An expected profile version and
payload-bound command receipt provide optimistic concurrency and exact replay. SQL application
state, archives, browser profiles, secrets, operational receipts, and deletion records are never
accepted by this path; the broader lifecycle export remains a non-restorable audit/backup artifact.

Synthetic confirmation is produced by a backend-owned executor dependency; clients provide only
the one-time authorization and acknowledge the synthetic fixture. Authorization consumption uses
a conditional database update so concurrent workers cannot both claim the same record, while a
matching idempotency-key retry returns the persisted outcome.

Authorization runs a no-write gate preflight before sealing artifacts. Required CV and cover-letter
sources fail closed instead of being skipped. A successful execution never rewrites its pre-submit
archive: it creates a separately hashed confirmed v2 archive containing backend confirmation HTML,
a final receipt which truthfully marks confirmation screenshots unavailable, a refreshed audit,
and a final manifest. No placeholder image is fabricated. Both versions remain recursively
verifiable.

Runtime job analysis crosses a provider-neutral agent boundary using only a minimal scoring-policy
projection. The service holds the candidate lifecycle fence across analysis, binds candidate,
profile, job-version, source-payload, normalized-job, and policy hashes, and requires exact semantic
agreement with deterministic dimension scores, evidence, contributions, totals, thresholds, and
blockers before persistence. Provider, model, and prompt identity are assigned by the service;
agent-supplied identity cannot enter the durable audit record.

Material generation is driven by the immutable candidate snapshot. Experience and project groups
are ranked against the normalized job and capped by candidate policy; role-template selection is
allowlisted. Cover-letter inclusion records the exact source/config/priority/motivation reason and
word bounds. That decision, template, selected fact groups, generator version, and exact job-version
hash are persisted on the application and mirrored into score rationale. Later configuration or
job drift therefore cannot silently change revision, gate, or archive requirements; malformed
policy denies. Legacy applications are backfilled according to whether a cover-letter document
already exists.

## Local authorization

Runtime defaults require a signed local bearer session plus CSRF for mutations. Candidate IDs from
paths, queries, and bodies must be session-owned. Artifact bytes are served only after candidate
authorization and hash verification. Local-session issuance assumes localhost trust; it is not a
substitute for hosted multi-user identity and encrypted storage.

## Durable operations and correspondence

The scheduler creates candidate-scoped SQL tasks with deterministic bucket keys. General and
browser workers claim disjoint task-kind allowlists under a lease, recover expired work, retry with
a bound, and reject keys reused for different payloads. Redis publishes process health; SQL remains
the task source of truth.

Correspondence ingestion stores message hashes rather than raw bodies, associates only on unique
deterministic evidence, and permits unmatched candidate-owned records. Valid interview, rejection,
and offer messages advance the explicit application state machine and create dashboard
notifications. Interview packages are immutable derivatives of the exact persisted CV, cover
letter, answers, job evidence, score rationale, and associated message subjects; no reply or send
capability exists.

- Candidate data is configuration, never an engine constant.
- Generated claims must cite candidate evidence IDs.
- Agent outputs remain proposals until deterministic validation and review complete.
- Browser/session records are auditable and candidate-scoped.
- Security events are append-oriented records.
- Secrets and raw credentials do not belong in candidate files or archives.
- No component is allowed to bypass CAPTCHA or anti-bot protections.
