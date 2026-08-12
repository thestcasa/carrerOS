"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { JobRoleCategory, JobSummary } from "@/lib/types";
import { matchStatus } from "@/lib/product-semantics";
import { BottomSheet } from "./BottomSheet";
import { ProductIcon } from "./ProductIcon";

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
  const [view, setView] = useState<"for_you" | "all" | "shortlisted">("for_you");
  const [sort, setSort] = useState<"match" | "newest">("match");
  const [minimumScore, setMinimumScore] = useState(0);
  const [filtersOpen, setFiltersOpen] = useState(false);

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
        (!showAvailableOnly || job.hard_blockers.length === 0) &&
        (job.score ?? 0) >= minimumScore &&
        (view === "all" ||
          (view === "shortlisted" && job.state === "shortlisted") ||
          (view === "for_you" && job.role_category !== "non_target"))
      );
    }).sort((left, right) => sort === "match"
      ? (right.score ?? -1) - (left.score ?? -1)
      : (right.posted_at ?? "").localeCompare(left.posted_at ?? ""));
  }, [category, jobs, minimumScore, query, showAvailableOnly, sort, view]);

  return (
    <section aria-labelledby="jobs-heading">
      <div className="section-heading">
        <div><p className="eyebrow">Your matches</p><h2 id="jobs-heading">Jobs</h2></div>
        <p>{filtered.length} of {jobs.length} opportunities shown.</p>
      </div>

      <div className="jobs-toolbar">
        <label className="search-control">
          <ProductIcon name="search" /><span className="sr-only">Search jobs</span>
          <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search jobs" />
        </label>
        <button className="icon-button filter-button" type="button" onClick={() => setFiltersOpen(true)} aria-label="Open job filters">
          <ProductIcon name="filter" />{(minimumScore > 0 || category !== "all" || showAvailableOnly) ? <span className="filter-active-dot" /> : null}
        </button>
      </div>
      <div className="segmented-control" aria-label="Job view">
        <button type="button" aria-pressed={view === "for_you"} onClick={() => setView("for_you")}>For you</button>
        <button type="button" aria-pressed={view === "all"} onClick={() => setView("all")}>All jobs</button>
        <button type="button" aria-pressed={view === "shortlisted"} onClick={() => setView("shortlisted")}>Shortlisted</button>
      </div>
      <div className="results-bar"><span>{filtered.length} {filtered.length === 1 ? "job" : "jobs"}</span><label>Sort <select aria-label="Sort jobs" value={sort} onChange={(event) => setSort(event.target.value as "match" | "newest")}><option value="match">Best match</option><option value="newest">Newest</option></select></label></div>

      <details className="advanced-diagnostics jobs-filter-panel" aria-label="Job filters">
        <summary>Desktop filters</summary>
        <div className="field-grid">
          <label className="form-field">
            <span>Search is available above</span>
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

      <BottomSheet open={filtersOpen} title="Filters" description="Narrow these results using real job analysis data." onClose={() => setFiltersOpen(false)}>
        <label className="range-field"><span>Minimum match score <strong>{minimumScore}</strong></span><input type="range" min="0" max="100" step="5" value={minimumScore} onChange={(event) => setMinimumScore(Number(event.target.value))} /></label>
        <label className="form-field"><span>Fit</span><select value={category} onChange={(event) => setCategory(event.target.value as JobRoleCategory | "all")}><option value="all">All fits</option>{Object.entries(categoryLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
        <label className="boolean-field"><input type="checkbox" checked={showAvailableOnly} onChange={(event) => setShowAvailableOnly(event.target.checked)} /><span><strong>Ready to prepare</strong><small>Hide jobs with unresolved blockers.</small></span></label>
        <button className="button primary sheet-primary" type="button" onClick={() => setFiltersOpen(false)}>Show {filtered.length} {filtered.length === 1 ? "job" : "jobs"}</button>
        <button className="text-button sheet-reset" type="button" onClick={() => { setMinimumScore(0); setCategory("all"); setShowAvailableOnly(false); }}>Clear filters</button>
      </BottomSheet>

      {filtered.length === 0 ? (
        <div className="empty-state">
          <h2>No jobs match these filters</h2>
          <p>Try changing your search or filters.</p>
        </div>
      ) : (
        <div className="job-card-grid jobs-card-grid" role="list" aria-label="Available jobs">
          {filtered.map((job) => {
            const match = matchStatus(job.score, job.role_category, job.proposed_action);
            return (
            <article className="job-list-card" role="listitem" key={job.job_id}>
              <Link className="job-card-main-link" href={`/jobs/${job.job_id}?candidate_id=${encodeURIComponent(candidateId)}`}>
                <div className={`match-badge semantic-${match.tone}`}><strong>{job.score ?? "—"}</strong><span>{match.label}</span></div>
                <div className="job-card-copy">
                  <p className="eyebrow">{job.company}</p>
                  <h3>{job.title}</h3>
                  <p className="muted">{job.location ?? "Location not provided"}</p>
                  <div className="job-card-tags">
                    {job.remote_policy ? <span>{job.remote_policy.replaceAll("_", " ")}</span> : null}
                    {job.employment_type ? <span>{job.employment_type.replaceAll("_", " ")}</span> : null}
                    {job.seniority ? <span>{job.seniority.replaceAll("_", " ")}</span> : null}
                  </div>
                </div>
                <ProductIcon name="chevron" />
              </Link>
              <div className="job-card-detail-row">
                <span>Posted {dateLabel(job.posted_at)}</span>
                <span>{job.salary_display ?? (job.role_category ? categoryLabels[job.role_category] : "Not classified")}</span>
              </div>
              {job.hard_blockers.length ? (
                <p className="issue-text">Needs attention: {job.hard_blockers.join(", ")}</p>
              ) : null}
              {job.possible_duplicate ? <p className="issue-text">Possible duplicate</p> : null}
              {job.stale ? (
                <p className="issue-text">Check the employer page before continuing.</p>
              ) : null}
              <div className="job-card-actions">
                <Link
                  className="button primary"
                  href={`/jobs/${job.job_id}?candidate_id=${encodeURIComponent(candidateId)}`}
                  aria-label={`Review ${job.title} at ${job.company}`}
                >
                  Review job
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
          );})}
        </div>
      )}
    </section>
  );
}
