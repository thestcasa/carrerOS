"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { JobRoleCategory, JobSummary } from "@/lib/types";

const categoryLabels: Record<JobRoleCategory, string> = {
  target: "Great fit",
  adjacent: "Possible fit",
  non_target: "Outside your targets",
};

function dateLabel(value: string | null) {
  if (!value) return "Not provided";
  return new Intl.DateTimeFormat("en", { dateStyle: "medium" }).format(new Date(value));
}

export function JobsInbox({ candidateId, jobs }: { candidateId: string; jobs: JobSummary[] }) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<JobRoleCategory | "all">("all");
  const [showAvailableOnly, setShowAvailableOnly] = useState(false);

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return jobs.filter((job) => {
      const matchesText =
        !needle ||
        `${job.company} ${job.title} ${job.location ?? ""}`
          .toLocaleLowerCase()
          .includes(needle);
      return (
        matchesText &&
        (category === "all" || job.role_category === category) &&
        (!showAvailableOnly || job.hard_blockers.length === 0)
      );
    });
  }, [category, jobs, query, showAvailableOnly]);

  return (
    <section aria-labelledby="jobs-heading">
      <div className="section-heading">
        <div><p className="eyebrow">Your matches</p><h2 id="jobs-heading">Jobs</h2></div>
        <p>{filtered.length} of {jobs.length} opportunities shown.</p>
      </div>

      <details className="advanced-diagnostics jobs-filter-panel" aria-label="Job filters">
        <summary>Search and filters</summary>
        <div className="field-grid">
          <label className="form-field">
            <span>Search jobs</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Company, title, or location"
            />
          </label>
          <label className="form-field">
            <span>Fit</span>
            <select
              value={category}
              onChange={(event) => setCategory(event.target.value as JobRoleCategory | "all")}
            >
              <option value="all">All jobs</option>
              {Object.entries(categoryLabels).map(([value, label]) => (
                <option value={value} key={value}>{label}</option>
              ))}
            </select>
          </label>
          <label className="boolean-field">
            <input
              type="checkbox"
              checked={showAvailableOnly}
              onChange={(event) => setShowAvailableOnly(event.target.checked)}
            />
            <span>
              <strong>Ready to prepare</strong>
              <small>Hide jobs with unresolved blockers.</small>
            </span>
          </label>
        </div>
      </details>

      {filtered.length === 0 ? (
        <div className="empty-state">
          <h2>No jobs match these filters</h2>
          <p>Try changing your search or filters.</p>
        </div>
      ) : (
        <div className="job-card-grid jobs-card-grid" role="list" aria-label="Available jobs">
          {filtered.map((job) => (
            <article className="panel application-card job-card" role="listitem" key={job.job_id}>
              <div>
                <p className="eyebrow">{job.company}</p>
                <h3>{job.title}</h3>
                <p className="muted">
                  {job.location ?? "Location not provided"} ·{" "}
                  {job.remote_policy?.replaceAll("_", " ") ?? "Work mode not provided"}
                </p>
              </div>
              <dl className="compact-metadata">
                <div><dt>Match</dt><dd>{job.score ?? "Pending"}</dd></div>
                <div>
                  <dt>Fit</dt>
                  <dd>{job.role_category ? categoryLabels[job.role_category] : "Not classified"}</dd>
                </div>
                <div><dt>Posted</dt><dd>{dateLabel(job.posted_at)}</dd></div>
                <div><dt>Salary</dt><dd>{job.salary_display ?? "Not provided"}</dd></div>
              </dl>
              {job.hard_blockers.length ? (
                <p className="issue-text">Needs attention: {job.hard_blockers.join(", ")}</p>
              ) : null}
              {job.possible_duplicate ? <p className="issue-text">Possible duplicate</p> : null}
              {job.stale ? (
                <p className="issue-text">Check the employer page before continuing.</p>
              ) : null}
              <div className="card-actions">
                <Link
                  className="button primary"
                  href={`/jobs/${job.job_id}?candidate_id=${encodeURIComponent(candidateId)}`}
                  aria-label={`Prepare application for ${job.title} at ${job.company}`}
                >
                  Prepare application
                </Link>
                <a
                  className="button secondary"
                  href={job.source_url}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={`Apply manually for ${job.title} at ${job.company} on the official site`}
                >
                  Apply manually
                </a>
              </div>
              <small className="muted">
                Manual applications happen on the employer&apos;s site and are not recorded as
                submitted here.
              </small>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
