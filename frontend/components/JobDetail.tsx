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
              <dd>
                {item.points > 0 ? "+" : ""}
                {item.points}: {item.explanation}
              </dd>
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
  return (
    <div className="readiness-layout">
      <section className="overview-grid" aria-label="Job decision summary">
        <article className="panel">
          <p className="eyebrow">Candidate score</p>
          <span className="large-metric">{job.score ?? "—"}</span>
          <p>
            {job.role_category?.replaceAll("_", " ") ?? "Unclassified"}; confidence{" "}
            {job.classification_confidence === null
              ? "unknown"
              : `${Math.round(job.classification_confidence * 100)}%`}
            .
          </p>
        </article>
        <article className="panel">
          <p className="eyebrow">Proposed action</p>
          <h2>{job.proposed_action.replaceAll("_", " ")}</h2>
          <p>This proposal does not authorize or submit an application.</p>
        </article>
        <article className="panel">
          <p className="eyebrow">Source</p>
          <h2>{job.source_verified ? "Verified" : "Unverified"}</h2>
          <p>
            {job.source_trust_level}; checked {job.verified_open_at ?? "never"}.
          </p>
          <a href={job.source_url} target="_blank" rel="noreferrer">
            Open official source ↗
          </a>
        </article>
      </section>

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
          <div><dt>Employment type</dt><dd>{present(job.employment_type)}</dd></div>
          <div><dt>Seniority</dt><dd>{present(job.seniority)}</dd></div>
          <div><dt>Posted</dt><dd>{present(job.posted_at)}</dd></div>
          <div><dt>Deadline</dt><dd>{present(job.deadline)}</dd></div>
          <div><dt>Expected start</dt><dd>{present(job.expected_start_date)}</dd></div>
        </dl>
      </section>

      <section className="panel" aria-labelledby="eligibility-heading">
        <p className="eyebrow">Extracted constraints</p>
        <h2 id="eligibility-heading">Employment and eligibility requirements</h2>
        <dl className="metadata-list">
          <div>
            <dt>Required experience</dt>
            <dd>{experienceRange(job.required_experience_years_min, job.required_experience_years_max)}</dd>
          </div>
          <div><dt>Visa requirements</dt><dd>{present(job.visa_requirements)}</dd></div>
          <div>
            <dt>Work authorization</dt>
            <dd>{present(job.work_authorization_requirements)}</dd>
          </div>
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
                : "None extracted"}
            </dd>
          </div>
        </dl>
      </section>

      <section className="panel action-panel" aria-labelledby="job-actions-heading">
        <div>
          <p className="eyebrow">Candidate workflow</p>
          <h2 id="job-actions-heading">Review actions</h2>
          <p className="muted">
            These actions record review state only. They cannot authorize or submit an application.
          </p>
        </div>
        <div className="editor-actions">
          <button className="button secondary" disabled={Boolean(busyAction)} onClick={() => onAction?.("verify")}>
            {busyAction === "verify" ? "Verifying…" : "Verify source"}
          </button>
          <button className="button primary" disabled={Boolean(busyAction) || job.state === "shortlisted"} onClick={() => onAction?.("shortlist")}>
            {busyAction === "shortlist" ? "Shortlisting…" : "Shortlist"}
          </button>
          <button className="button secondary" disabled={Boolean(busyAction) || job.state === "ignored"} onClick={() => onAction?.("skip")}>
            {busyAction === "skip" ? "Skipping…" : "Skip job"}
          </button>
          <button className="button primary" disabled={Boolean(busyAction) || job.score === null || job.hard_blockers.length > 0} onClick={() => onAction?.("generate")}>
            {busyAction === "generate" ? "Generating…" : "Generate materials"}
          </button>
        </div>
        {actionError ? <p className="form-message error" role="alert">{actionError}</p> : null}
      </section>

      {job.hard_blockers.length ? (
        <section className="error-state" role="alert">
          <h2>Hard blockers</h2>
          <ul>{job.hard_blockers.map((item) => <li key={item}>{item}</li>)}</ul>
        </section>
      ) : null}

      <section aria-labelledby="requirements-heading">
        <div className="section-heading">
          <div><p className="eyebrow">Evidence</p><h2 id="requirements-heading">Requirement-by-requirement analysis</h2></div>
        </div>
        <div className="domain-list">
          {job.requirements.map((requirement) => (
            <article className="domain-row" key={`${requirement.kind}-${requirement.requirement}`}>
              <div>
                <h3>{requirement.requirement}</h3>
                <p className="field-path">{requirement.kind}</p>
                {requirement.evidence.map((evidence) => <p key={evidence}>{evidence}</p>)}
              </div>
              <strong>{requirement.status}</strong>
            </article>
          ))}
        </div>
      </section>

      <section className="overview-grid" aria-label="Descriptions">
        <article className="panel">
          <p className="eyebrow">Untrusted source content</p><h2>Original description</h2>
          <p style={{ whiteSpace: "pre-wrap" }}>{job.description_raw}</p>
        </article>
        <article className="panel">
          <p className="eyebrow">Structured extraction</p><h2>Normalized description</h2>
          <p style={{ whiteSpace: "pre-wrap" }}>{job.description_normalized}</p>
        </article>
        <article className="panel">
          <p className="eyebrow">Salary</p>
          <h2>{salaryRange(job)}</h2>
          <p>{job.salary_evidence ?? "No salary evidence found."}</p>
          <dl className="metadata-list">
            <div><dt>Minimum</dt><dd>{present(job.salary_min)}</dd></div>
            <div><dt>Maximum</dt><dd>{present(job.salary_max)}</dd></div>
            <div><dt>Currency</dt><dd>{present(job.salary_currency)}</dd></div>
            <div><dt>Period</dt><dd>{present(job.salary_period)}</dd></div>
            <div><dt>Source</dt><dd>{present(job.salary_source)}</dd></div>
          </dl>
          <p>
            Confidence: {job.salary_confidence === null ? "unknown" : `${Math.round(job.salary_confidence * 100)}%`}
          </p>
        </article>
      </section>

      <div className="overview-grid">
        <Contributions title="Score dimensions" items={job.score_dimensions} />
        <Contributions title="Bonuses" items={job.bonuses} />
        <Contributions title="Penalties" items={job.penalties} />
      </div>

      <section className="overview-grid" aria-label="Selected evidence and security">
        <article className="panel">
          <h2>Selected experience</h2><ul>{job.selected_experience.map((item) => <li key={item}>{item}</li>)}</ul>
          <h2>Selected projects</h2><ul>{job.selected_projects.map((item) => <li key={item}>{item}</li>)}</ul>
        </article>
        <article className="panel">
          <h2>Required skills</h2><p>{job.required_skills.join(", ") || "None extracted"}</p>
          <h2>Preferred skills</h2><p>{job.preferred_skills.join(", ") || "None extracted"}</p>
        </article>
        <article className="panel">
          <h2>Security findings</h2>
          {job.security_findings.length ? (
            <ul>{job.security_findings.map((finding) => <li key={finding.code}><strong>{finding.severity}:</strong> {finding.explanation}</li>)}</ul>
          ) : (
            <p>No findings recorded.</p>
          )}
        </article>
      </section>
    </div>
  );
}
