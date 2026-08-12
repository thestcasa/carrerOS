"use client";

import type { JobDetail as JobDetailData, ScoreContribution } from "@/lib/types";

function Contributions({ title, items }: { title: string; items: ScoreContribution[] }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {items.length ? (
        <dl className="metadata-list">
          {items.map((item) => (
            <div key={item.name}>
              <dt>{item.name.replaceAll("_", " ")}</dt>
              <dd>{item.points > 0 ? "+" : ""}{item.points}: {item.explanation}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="muted">None recorded.</p>
      )}
    </section>
  );
}

function present(value: string | number | null): string {
  return value === null || value === "" ? "Not provided" : String(value);
}

function experienceRange(minimum: number | null, maximum: number | null): string {
  if (minimum === null && maximum === null) return "Not provided";
  if (minimum !== null && maximum !== null) return `${minimum}–${maximum} years`;
  if (minimum !== null) return `${minimum}+ years`;
  return `Up to ${maximum} years`;
}

function salaryRange(job: JobDetailData): string {
  if (job.salary_display) return job.salary_display;
  if (job.salary_min === null && job.salary_max === null) return "Not disclosed";
  const amount =
    job.salary_min !== null && job.salary_max !== null
      ? `${job.salary_min}–${job.salary_max}`
      : job.salary_min !== null
        ? `${job.salary_min}+`
        : `Up to ${job.salary_max}`;
  return [job.salary_currency, amount, job.salary_period].filter(Boolean).join(" ");
}

export function JobDetail({
  job,
  busyAction,
  actionError,
  onAction,
}: {
  job: JobDetailData;
  busyAction?: string | null;
  actionError?: string | null;
  onAction?: (action: "verify" | "shortlist" | "skip" | "generate") => void;
}) {
  const canPrepare = job.score !== null && job.hard_blockers.length === 0;

  return (
    <div className="readiness-layout">
      <section className="panel action-panel job-primary-actions" aria-labelledby="job-actions-heading">
        <div>
          <p className="eyebrow">Choose how to continue</p>
          <h2 id="job-actions-heading">Apply for this job</h2>
          <p className="muted">
            Career OS can prepare tailored materials, or you can continue independently on the
            employer&apos;s official website.
          </p>
        </div>
        <div className="editor-actions">
          <button
            className="button primary"
            disabled={Boolean(busyAction) || !canPrepare}
            onClick={() => onAction?.("generate")}
          >
            {busyAction === "generate" ? "Preparing…" : "Prepare application"}
          </button>
          <a
            className="button secondary"
            href={job.source_url}
            target="_blank"
            rel="noreferrer"
          >
            Apply manually on official site
          </a>
        </div>
        <p className="muted">
          Opening the official site does not record an application or submission in Career OS.
        </p>
        {actionError ? <p className="form-message error" role="alert">{actionError}</p> : null}
      </section>

      {job.hard_blockers.length ? (
        <section className="error-state" role="alert">
          <h2>Before Career OS can prepare this application</h2>
          <ul>{job.hard_blockers.map((item) => <li key={item}>{item}</li>)}</ul>
          <p>You can still review the employer&apos;s official page and decide whether to apply manually.</p>
        </section>
      ) : null}

      <section className="overview-grid" aria-label="Job summary">
        <article className="panel">
          <p className="eyebrow">Match</p>
          <span className="large-metric">{job.score ?? "—"}</span>
          <p>{job.role_category?.replaceAll("_", " ") ?? "Not classified"}</p>
        </article>
        <article className="panel">
          <p className="eyebrow">Location and work mode</p>
          <h2>{job.location ?? "Not provided"}</h2>
          <p>{job.remote_policy?.replaceAll("_", " ") ?? "Work mode not provided"}</p>
        </article>
        <article className="panel">
          <p className="eyebrow">Compensation</p>
          <h2>{salaryRange(job)}</h2>
          <p>{job.employment_type?.replaceAll("_", " ") ?? "Employment type not provided"}</p>
        </article>
      </section>

      <section className="panel" aria-labelledby="job-description-heading">
        <p className="eyebrow">About the role</p>
        <h2 id="job-description-heading">Job description</h2>
        <p style={{ whiteSpace: "pre-wrap" }}>
          {job.description_normalized || job.description_raw}
        </p>
      </section>

      <section className="panel" aria-labelledby="eligibility-heading">
        <p className="eyebrow">Important requirements</p>
        <h2 id="eligibility-heading">Employment and eligibility requirements</h2>
        <dl className="metadata-list">
          <div>
            <dt>Required experience</dt>
            <dd>{experienceRange(job.required_experience_years_min, job.required_experience_years_max)}</dd>
          </div>
          <div><dt>Visa requirements</dt><dd>{present(job.visa_requirements)}</dd></div>
          <div><dt>Work authorization</dt><dd>{present(job.work_authorization_requirements)}</dd></div>
          <div>
            <dt>Required languages</dt>
            <dd>
              {job.required_languages.length
                ? job.required_languages
                    .map((item) =>
                      item.minimum_level
                        ? `${item.language} (${item.minimum_level} minimum)`
                        : item.language,
                    )
                    .join(", ")
                : "None specified"}
            </dd>
          </div>
        </dl>
      </section>

      {job.requirements.length ? (
        <section aria-labelledby="requirements-heading">
          <div className="section-heading">
            <div><p className="eyebrow">Your fit</p><h2 id="requirements-heading">Requirements</h2></div>
          </div>
          <div className="domain-list">
            {job.requirements.map((requirement) => (
              <article className="domain-row" key={`${requirement.kind}-${requirement.requirement}`}>
                <div>
                  <h3>{requirement.requirement}</h3>
                  {requirement.evidence.map((evidence) => <p key={evidence}>{evidence}</p>)}
                </div>
                <strong>{requirement.status}</strong>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      <section className="panel action-panel" aria-label="Save or skip job">
        <div>
          <p className="eyebrow">Keep your list organised</p>
          <h2>Save this opportunity for later</h2>
        </div>
        <div className="editor-actions">
          <button
            className="button secondary"
            disabled={Boolean(busyAction) || job.state === "shortlisted"}
            onClick={() => onAction?.("shortlist")}
          >
            {busyAction === "shortlist" ? "Saving…" : "Save job"}
          </button>
          <button
            className="button secondary"
            disabled={Boolean(busyAction) || job.state === "ignored"}
            onClick={() => onAction?.("skip")}
          >
            {busyAction === "skip" ? "Removing…" : "Not interested"}
          </button>
        </div>
      </section>

      <details className="advanced-diagnostics job-advanced-details">
        <summary>Advanced job analysis</summary>
        <div className="readiness-layout">
          <section className="panel" aria-labelledby="normalized-job-heading">
            <p className="eyebrow">Structured source record</p>
            <h2 id="normalized-job-heading">Normalized job metadata</h2>
            <dl className="metadata-list">
              <div><dt>External job ID</dt><dd>{job.external_job_id}</dd></div>
              <div><dt>Requisition ID</dt><dd>{present(job.requisition_id)}</dd></div>
              <div><dt>Normalized title</dt><dd>{present(job.normalized_title)}</dd></div>
              <div><dt>Normalized location</dt><dd>{present(job.normalized_location)}</dd></div>
              <div><dt>Company domain</dt><dd>{present(job.company_domain)}</dd></div>
              <div><dt>Company stage</dt><dd>{present(job.company_stage)}</dd></div>
              <div><dt>Team</dt><dd>{present(job.team)}</dd></div>
              <div><dt>Seniority</dt><dd>{present(job.seniority)}</dd></div>
              <div><dt>Posted</dt><dd>{present(job.posted_at)}</dd></div>
              <div><dt>Deadline</dt><dd>{present(job.deadline)}</dd></div>
              <div><dt>Expected start</dt><dd>{present(job.expected_start_date)}</dd></div>
            </dl>
          </section>

          <section className="panel action-panel" aria-label="Source verification">
            <div>
              <p className="eyebrow">Official source</p>
              <h2>{job.source_verified ? "Verified" : "Verification recommended"}</h2>
              <p className="muted">Last checked: {job.verified_open_at ?? "never"}.</p>
            </div>
            <button
              className="button secondary"
              disabled={Boolean(busyAction)}
              onClick={() => onAction?.("verify")}
            >
              {busyAction === "verify" ? "Verifying…" : "Verify source"}
            </button>
          </section>

          <section className="panel">
            <h2>Original source description</h2>
            <p style={{ whiteSpace: "pre-wrap" }}>{job.description_raw}</p>
          </section>

          <div className="overview-grid">
            <Contributions title="Score dimensions" items={job.score_dimensions} />
            <Contributions title="Bonuses" items={job.bonuses} />
            <Contributions title="Penalties" items={job.penalties} />
          </div>

          <section className="overview-grid" aria-label="Selected evidence and security">
            <article className="panel">
              <h2>Selected experience</h2>
              <ul>{job.selected_experience.map((item) => <li key={item}>{item}</li>)}</ul>
              <h2>Selected projects</h2>
              <ul>{job.selected_projects.map((item) => <li key={item}>{item}</li>)}</ul>
            </article>
            <article className="panel">
              <h2>Required skills</h2>
              <p>{job.required_skills.join(", ") || "None extracted"}</p>
              <h2>Preferred skills</h2>
              <p>{job.preferred_skills.join(", ") || "None extracted"}</p>
            </article>
            <article className="panel">
              <h2>Security findings</h2>
              {job.security_findings.length ? (
                <ul>
                  {job.security_findings.map((finding) => (
                    <li key={finding.code}>
                      <strong>{finding.severity}:</strong> {finding.explanation}
                    </li>
                  ))}
                </ul>
              ) : (
                <p>No findings recorded.</p>
              )}
            </article>
          </section>
        </div>
      </details>
    </div>
  );
}
