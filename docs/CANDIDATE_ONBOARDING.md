# Candidate Onboarding

CareerOS commits only the fictional `example_candidate`. Private candidate packages belong under
the configured candidates root and must not be added to a public repository.

Create a blocked draft with either the web candidate page or:

```bash
python -m app onboard --candidate fictional_friend --display-name "Fictional Friend" \
  --idempotency-key onboard-fictional-friend
```

The command copies schema and policy structure, then clears evidence, languages, certifications,
publications, and reusable answers. All section approvals, discovery, email tracking, and automatic
submission start disabled. Placeholder contact data uses the reserved `.invalid` domain.

Edit each domain in the web profile editor or import one validated JSON section at a time. Stable
fact IDs must not be reused. A fact is eligible for outward material only when its parent record and
the fact itself are approved, active, verified, publicly usable, and non-internal. Restricted
projects require an explicitly approved public summary. Sensitive answers also require explicit
auto-submit permission and a current validity window.

The profile page and CLI can extract a UTF-8 text CV into a review draft:

```bash
python -m app import-cv --candidate fictional_friend --file /private/path/cv.txt \
  --idempotency-key extract-fictional-cv
python -m app import-cv --candidate fictional_friend --file /private/path/cv.txt --apply \
  --idempotency-key apply-fictional-cv
```

Imports are limited to 2 MiB, 5,000 lines, and bounded structured output. The parser records the
source SHA-256 but does not retain the raw CV. It recognizes pipe-delimited rows under `EDUCATION`
and `EXPERIENCE` headings,
uses deterministic stable IDs, and stores imported items as restricted and unapproved. Applying a
draft creates one candidate version; readiness remains blocked until every imported fact is
reviewed and explicitly approved. Reapplying the same import is idempotent.

PDF import remains disabled until parsing can run in a CPU/memory/time-constrained worker.
Converting a private CV to UTF-8 text locally is the supported safe path in this build.

Run validation and capability readiness after changes:

```bash
python -m app validate-candidate --candidate fictional_friend
python -m app readiness --candidate fictional_friend
python -m app export-candidate --candidate fictional_friend
```

Discovery and automatic submission remain separate controls. Enabling either in a file does not
bypass backend readiness, the deterministic submission gate, archive creation, rate limits,
emergency stop, or one-time authorization consumption.
