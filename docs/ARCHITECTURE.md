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

The `ApplicationOrchestrator` controls sequencing, but cannot authorize submission. Only `SubmissionGate` can issue a `SubmissionAuthorization`. The gate is deterministic, defaults to denial, and treats every absent, unknown, or false prerequisite as failure. The future browser worker will accept an authorization but will never score suitability, invent answers, generate documents, or bypass CAPTCHA/anti-bot controls.

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
     +--> SubmissionGate ----> authorization or denial
                                  |
                                  v
                         future browser worker
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

The loader rejects path traversal, missing files, candidate-ID mismatches, malformed dates, duplicate stable IDs, and internally contradictory target/block lists. Pydantic v2 models are strict and forbid unknown fields. The `readiness` command adds operational checks such as minimum evidence, languages, targets, scoring weights, and legal-status approval.

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

State changes are recorded as candidate-scoped application events. Persistence-level uniqueness on `(candidate_id, application_id, idempotency_key)` protects replay behavior.

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

`global_jobs` stores the current candidate-neutral normalized view. `job_versions` is append-only
and records every content change by canonical payload hash, while repeated unchanged discovery is
idempotent. Candidate evaluation is stored separately in `candidate_job_scores`, allowing the same
global job to receive different classifications, scores, evidence, blockers, and proposed actions
for different candidate configurations. Candidate thresholds and weights remain configuration,
not engine constants.

Candidate inbox state is isolated in `candidate_job_decisions`. Every analyze, verify, shortlist,
or skip mutation records a durable `candidate_job_commands` receipt keyed by candidate and caller
idempotency key; discovery has its own durable receipt. Reuse with different input fails with a
stable conflict. Injection findings block analysis and enter the candidate security ledger. Worker and scheduler are distinct Compose processes that
advertise health through Redis, and external ports bind to localhost by default.

## Trust and privacy decisions

## Materials and synthetic browser dry runs

The materials boundary consumes explicit approved facts and exact approved-answer keys. Every
generated claim carries evidence IDs; hashes, target-company validation, and independent review
fail closed before an immutable draft version can progress. Draft storage uses candidate and
application path segments, exclusive version creation, and content-hash verification.

The browser dry-run boundary accepts a finalized structured package, maps only known synthetic
fields, validates uploads against allowlisted artifact paths, re-reads filled values, and extracts
the final page without a submit operation. CAPTCHA and OTP markers persist a visible human action,
screenshot, page snapshot, and same-session reference. Completion resumes that recorded session
before final gate validation. No live final click exists in this build.

## Local authorization

Runtime defaults require a signed local bearer session plus CSRF for mutations. Candidate IDs from
paths, queries, and bodies must be session-owned. Artifact bytes are served only after candidate
authorization and hash verification. Local-session issuance assumes localhost trust; it is not a
substitute for hosted multi-user identity and encrypted storage.

## Durable operations and correspondence

The scheduler creates candidate-scoped SQL tasks with deterministic bucket keys. Workers claim
tasks under a lease, recover expired work, retry with a bound, and reject keys reused for different
payloads. Redis publishes process health; SQL remains the task source of truth.

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
