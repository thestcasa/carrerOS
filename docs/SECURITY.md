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
rate-limit evasion are forbidden. This repository has no live final-click implementation.
Human-action responses expose only exact authenticated screenshot artifact references, normalized
safe origins, and status. They never expose browser profile paths, cookies, CDP/WebSocket URLs, or
transport credentials. The local open-session command is an idempotent handshake, not a takeover
capability; the UI reports interactive transport as unavailable until a secure broker exists.

Browser workers hold the candidate lifecycle fence for the complete external attempt and evidence
publication, preventing erasure races from recreating candidate files. Attempt screenshots and
HTML are accepted only from exact candidate/session leaf names and are opened without following
symlinks. Lease-lost attempt evidence is removed before the stale result is discarded; referenced
evidence remains immutable, hash-verified, and included in bounded lifecycle exports.
