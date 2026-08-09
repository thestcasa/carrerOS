Build carrerOS autonomously from the current repository state until the complete `carreros_project_spec` definition of done has been satisfied.

`carreros_project_spec` is the authoritative product specification.

Immediate priority for the next run:

1. Treat the local first-version website as the next incomplete milestone. Simplify the normal user
   pipeline from candidate readiness through job selection, materials review, safe dry run, human
   action, and explicit controlled approval. Each stage needs one clear next action and plain language.
2. Make autonomy blockers actionable but evidence-backed:
   - `no_tested_ats_adapter` closes only from a durable passing synthetic adapter acceptance record;
   - `dry_run_acceptance_not_passed` closes only from passing candidate-scoped dry-run/browser evidence;
   - `explicit_confirmation_missing` gets an explicit unchecked, consequence-aware, audited user flow
     after the first two prerequisites pass. Never confirm autonomy for the user.
3. Docker is available in WSL. Repair the scheduler failure
   `idempotency key was used for a different task`, then re-run Compose and the committed Playwright
   suite. Record exact health and browser results instead of retaining stale environment claims.
4. Add non-destructive detection/recovery for stale fictional candidate volumes. Never delete Docker
   volumes or overwrite unknown candidate data to make validation pass.
5. Keep manual approval as the first-version default. Do not enable live controlled submission, perform
   a real final click, contact an employer, or weaken SubmissionGate/readiness checks.

Do not restart completed milestones. Use `docs/AUTONOMOUS_STATUS.md` and
`docs/AUTONOMOUS_BUILD_PLAN.md` for the exact current checkpoint and acceptance tests.

Before making changes:

1. Read `AGENTS.md`.
2. Read the full project specification.
3. Read the architecture, implementation plan, existing milestone documents, and current autonomous status files.
4. Inspect the current branch, Git history, working tree, migrations, backend, frontend, tests, Docker configuration, and existing implementation conventions.
5. Confirm internally which requirements and milestones are already complete.
6. Create or update `docs/AUTONOMOUS_BUILD_PLAN.md` and `docs/AUTONOMOUS_STATUS.md`.

Then continue immediately into implementation.

Do not stop after planning, describing the architecture, listing tasks, producing a status report, or completing only one implementation phase.

Use a persistent execution plan. Keep it updated as work progresses so a future Codex session can continue from the repository without needing conversation history.

Work through the next incomplete milestone and then continue through subsequent milestones until the complete project specification is implemented, subject to the safety and scope constraints in the repository.

Use subagents where they improve reliability or speed. Good subagent tasks include:

* repository exploration;
* provider or library research;
* backend and frontend test analysis;
* security review;
* bounded implementation work with clearly separated file ownership;
* documentation review;
* final diff review.

The primary agent must remain responsible for:

* architecture;
* shared domain models and API contracts;
* integration;
* database migrations;
* resolving conflicting subagent proposals;
* end-to-end verification;
* final commits.

Do not allow multiple agents to make overlapping changes to the same files.

For every implementation phase:

1. inspect the relevant existing code;
2. implement the smallest coherent end-to-end slice;
3. add or update deterministic tests;
4. run formatting, linting, typing, tests, migrations, and builds as applicable;
5. diagnose and repair failures;
6. update documentation and autonomous status;
7. review the diff;
8. continue to the next incomplete requirement.

Do not ask the user for confirmation or next steps. Resolve non-critical ambiguity using the most conservative interpretation consistent with the project specification, existing architecture, and security boundaries. Record important decisions in the execution plan.

Do not:

* introduce real candidate data;
* commit credentials or secrets;
* bypass CAPTCHA;
* manipulate ATS systems;
* submit live applications;
* contact employers;
* bypass SubmissionGate;
* silently weaken validation or tests;
* claim verification that was not actually executed.

Use fictional and deterministic data whenever external services or credentials are unavailable.

If Docker, a browser connector, a provider API, or another external dependency is unavailable, document the exact limitation and continue all independent implementation and verification work.

Commit coherent completed milestones using conventional commit messages. Do not commit failing or partially integrated work unless it is explicitly marked as a recovery checkpoint and the repository remains understandable and resumable.

Before declaring completion:

* inspect every requirement in `carreros_project_spec`;
* verify database migrations;
* verify backend and frontend quality gates;
* verify the fictional local workflow;
* inspect the final Git diff;
* check that no secret or real candidate data is present;
* update all architecture, setup, and implementation documentation;
* ensure the working tree is clean after the final commit.

When all requirements are implemented and verified, provide a final implementation report and end with exactly:

BUILD_COMPLETE

If a hard external blocker prevents all further useful implementation, document the blocker and end with exactly:

BUILD_BLOCKED
