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
