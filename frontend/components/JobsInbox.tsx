"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { JobRoleCategory, JobSummary, JobWorkflowState } from "@/lib/types";

const stateLabels: Record<JobWorkflowState, string> = {
  discovered: "Discovered",
  saved: "Saved",
  ignored: "Ignored",
  blocked: "Blocked",
  shortlisted: "Shortlisted",
};

const categoryLabels: Record<JobRoleCategory, string> = {
  target: "Configured target",
  adjacent: "Configured adjacent",
  non_target: "Non-target",
};

function dateLabel(value: string | null) {
  if (!value) return "Unknown";
  return new Intl.DateTimeFormat("en", { dateStyle: "medium" }).format(new Date(value));
}

export function JobsInbox({ candidateId, jobs }: { candidateId: string; jobs: JobSummary[] }) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<JobRoleCategory | "all">("all");
  const [state, setState] = useState<JobWorkflowState | "all">("all");
  const [blockersOnly, setBlockersOnly] = useState(false);

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return jobs.filter((job) => {
      const matchesText = !needle || `${job.company} ${job.title} ${job.location ?? ""}`.toLocaleLowerCase().includes(needle);
      return matchesText && (category === "all" || job.role_category === category) &&
        (state === "all" || job.state === state) && (!blockersOnly || job.hard_blockers.length > 0);
    });
  }, [blockersOnly, category, jobs, query, state]);

  return (
    <section aria-labelledby="jobs-heading">
      <div className="section-heading">
        <div><p className="eyebrow">Candidate-scoped discovery</p><h2 id="jobs-heading">Jobs inbox</h2></div>
        <p>{filtered.length} of {jobs.length} jobs shown. Analysis is informational; there is no submission action here.</p>
      </div>
      <div className="panel" aria-label="Job filters">
        <div className="field-grid">
          <label className="form-field"><span>Search jobs</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Company, title, or location" /></label>
          <label className="form-field"><span>Role category</span><select value={category} onChange={(event) => setCategory(event.target.value as JobRoleCategory | "all")}><option value="all">All categories</option>{Object.entries(categoryLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
          <label className="form-field"><span>Inbox state</span><select value={state} onChange={(event) => setState(event.target.value as JobWorkflowState | "all")}><option value="all">All states</option>{Object.entries(stateLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
          <label className="boolean-field"><input type="checkbox" checked={blockersOnly} onChange={(event) => setBlockersOnly(event.target.checked)} /><span><strong>Hard blockers only</strong><small>Show jobs that cannot currently progress.</small></span></label>
        </div>
      </div>
      {filtered.length === 0 ? <div className="empty-state"><h2>No jobs match these filters</h2><p>Adjust the filters; no job state has been changed.</p></div> : (
        <div className="domain-list" role="list" aria-label="Discovered jobs">
          {filtered.map((job) => (
            <article className="domain-row" role="listitem" key={job.job_id}>
              <div>
                <p className="eyebrow">{job.company}</p><h3>{job.title}</h3>
                <p className="field-path">{job.location ?? "Location not provided"} · {job.remote_policy ?? "Remote policy unknown"} · {job.ats_platform ?? job.source}</p>
                <p>{job.role_category ? categoryLabels[job.role_category] : "Unclassified"} · Score {job.score ?? "Pending"} · {stateLabels[job.state]}</p>
                {job.hard_blockers.length ? <p className="issue-text">Blocking: {job.hard_blockers.join(", ")}</p> : null}
                {job.possible_duplicate ? <p className="issue-text">Possible duplicate</p> : null}
                {job.stale ? <p className="issue-text">Source needs freshness verification</p> : null}
              </div>
              <div className="domain-action">
                <span>Verified {dateLabel(job.verified_open_at)}</span>
                <Link href={`/jobs/${job.job_id}?candidate_id=${encodeURIComponent(candidateId)}`} aria-label={`Review ${job.title} at ${job.company}`}>Review analysis →</Link>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
