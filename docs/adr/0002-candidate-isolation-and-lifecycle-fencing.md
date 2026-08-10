# ADR 0002: Candidate-scoped isolation and lifecycle fencing

- Status: Accepted
- Date: 2026-08-10

## Context

Candidate configuration, generated documents, browser profiles, workflow state, and audit evidence
have different storage lifecycles. An application-level filter alone cannot prevent accidental
cross-candidate relationships, stale writers after deletion, or filesystem path confusion.

## Decision

Every candidate-owned database row carries a non-null `candidate_id`; composite foreign keys and
database triggers enforce same-candidate relationships and deletion tombstones. Services acquire a
candidate lifecycle fence before publishing filesystem or database mutations. Candidate paths are
resolved beneath explicit roots, reject traversal and symlink escape, and bind artifacts to hashes.

Configuration changes are versioned and payload-idempotent. Export is bounded; deletion is explicit,
audited, and recoverable after partial interruption. Docker images contain only the committed
fictional fixture, while mounted candidate volumes are inspected without automatic overwrite or
deletion.

## Consequences

- Cross-candidate access fails at both authorization and persistence boundaries.
- Operations carry more explicit candidate identity and transaction coordination.
- Stale or unknown mounted data blocks automatic repair and requires reviewed recovery.
- Hosted deployment still requires a managed identity, encryption, and tenant-isolated execution
  environment; these local controls do not claim to provide that infrastructure.
