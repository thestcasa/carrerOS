# ADR 0001: Deterministic submission authority

- Status: Accepted
- Date: 2026-08-10

## Context

CareerOS analyzes untrusted job content and uses bounded agents to score jobs and prepare material.
Those components are probabilistic or provider-dependent and must never acquire submission power.
A final click is irreversible and may be ambiguous after a network failure.

## Decision

Only `SubmissionGate` can issue a short-lived authorization or one-use final-click permit. Agent,
browser-fill, scheduler, and UI processes can propose or queue work but cannot mint that authority.
The gate denies missing, stale, unapproved, mismatched, or unarchived evidence. Authorization is
bound to the candidate, application state/version, exact reviewed package, adapter, and target.
Crossing the click boundary is durable and cannot be retried after an unknown outcome.

The local product defaults to manual approval. Controlled execution is absent from default Compose
and requires both a process switch and candidate policy. CAPTCHA, OTP, and identity checks always
create human work; no component may bypass them.

## Consequences

- LLM/provider compromise cannot directly submit an application.
- More evidence must be persisted and revalidated at every trust boundary.
- Ambiguous post-click outcomes require human reconciliation instead of automated retry.
- New ATS adapters need synthetic acceptance evidence and a deployment security review.
