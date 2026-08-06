# Security model

Career OS treats candidate data, external job content, browser sessions, and final submission as
separate trust zones. LLM agents can analyze and propose material but have no submission method.
Only `SubmissionGate` can issue a short-lived authorization, and its durable record is consumed
once. Missing or uncertain inputs deny.

External ATS payloads must pass HTTPS/domain validation and prompt-injection scanning. Findings are
stored in the candidate security ledger and block analysis. Uploads must be inside the candidate's
runtime tree, hash allowlisted, and unchanged. Composite database constraints prevent child rows
from referencing another candidate's application or score.

The local API uses signed bearer sessions and CSRF tokens. Hosted deployments still require a real
identity provider, encrypted candidate storage, isolated browser workers, key-managed secrets,
administrative audit, and edge rate limiting. Never place credentials in candidate files,
archives, fixtures, logs, or Git.

CAPTCHA, OTP, magic links, and identity checks always pause and create a human action in the same
session. CAPTCHA farms, fingerprint spoofing, hidden ATS text, fake identities, and anti-bot or
rate-limit evasion are forbidden.
Human-action responses expose only exact authenticated screenshot artifact references, normalized
safe origins, and status. They never expose browser profile paths, cookies, CDP/WebSocket URLs, or
transport credentials. The local open-session command is an idempotent handshake, not a takeover
capability; the UI reports interactive transport as unavailable until a secure broker exists.

Browser workers hold the candidate lifecycle fence for the complete external attempt and evidence
publication, preventing erasure races from recreating candidate files. Attempt screenshots and
HTML are accepted only from exact candidate/session leaf names and are opened without following
symlinks. Lease-lost attempt evidence is removed before the stale result is discarded; referenced
evidence remains immutable, hash-verified, and included in bounded lifecycle exports.

Controlled Greenhouse submission is a separate trust zone. It requires a process-level switch,
candidate-level automatic-submission opt-in, approval-required or fully ready autonomous mode, an
allowed and tested adapter, fresh source proof, exact package and destination hashes, rate limits,
and a gate-issued authorization. The API only queues the task. General and dry-run workers cannot
claim it, and the controlled worker is absent from default Compose.

The adapter repopulates and rechecks exact snapshot-derived first/last name and email values plus
the hash-verified reviewed CV after reopening the browser profile. Every additional visible input,
select, or textarea is unsupported and fails closed. CAPTCHA and OTP stop before authorization
consumption, pause the browser session, and create a human action.

Immediately before an outward effect, one transaction consumes the authorization, persists exact
pre-click screenshot/page hashes, and moves the attempt across an irreversible click boundary.
`SubmissionGate` then issues a 30-second in-memory permit bound to that committed proof and a
random nonce whose hash alone is stored. The Greenhouse adapter consumes the permit before its one
click; only then does the executor open its allowance for at most one same-origin POST. A timeout,
crash, missing confirmation, or
abandoned lease after arming becomes `UNKNOWN_AFTER_CLICK`, opens an immediate human action, and
can never be automatically retried. Armed and unknown attempts count conservatively against rate
limits.
