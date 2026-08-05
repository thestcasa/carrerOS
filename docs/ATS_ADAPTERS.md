# ATS adapters

Greenhouse, Lever, and Ashby adapters normalize deterministic provider payloads into one
candidate-neutral job schema. Adapters accept only HTTPS provider domains (including legitimate
subdomains), reject credentials/fragments/cross-domain application URLs, preserve raw source data,
and strip markup only into a separate normalized description.

External text never becomes instructions. The security scanner records stable findings for policy
override, secret exfiltration, safety bypass, local-file access, and hidden ATS manipulation.
Candidate classification and scoring happen after normalization and use only that candidate's
configuration. Engine code exposes generic `target`, `adjacent`, and `non_target` categories; it
does not hard-code a pilot's AI/ML taxonomy.

Tests and CLI discovery use fixtures. Adding a provider requires strict contracts, URL allowlists,
append-only version tests, prompt-injection cases, and a candidate-independent parser. Provider
credentials and live application submission do not belong in adapters.
