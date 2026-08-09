"use client";

import Link from "next/link";
import { useState } from "react";
import type { ApplicationState, ApplicationSummary } from "@/lib/types";
import { StatusPill } from "./StatusPill";

const lanes: Array<{ label: string; states: ApplicationState[] }> = [
  { label: "Preparing", states: ["discovered", "normalized", "security_check", "classified", "scored", "shortlisted", "candidate_snapshot_created", "materials_generating", "materials_ready"] },
  { label: "Waiting for approval", states: ["review_pending", "review_failed"] },
  { label: "Form filling", states: ["application_started", "form_filling", "final_validation"] },
  { label: "Human action required", states: ["human_action_required"] },
  { label: "Ready to submit", states: ["ready_to_submit", "submitting"] },
  { label: "Recorded outcomes", states: ["submitted", "confirmed", "rejected", "interview", "offer", "failed_retryable", "failed_final", "closed", "withdrawn", "unknown_after_click", "skipped"] },
];

function ageLabel(value: string): string {
  const milliseconds = Date.now() - new Date(value).getTime();
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return "just now";
  const hours = Math.floor(milliseconds / 3_600_000);
  if (hours < 1) return `${Math.max(1, Math.floor(milliseconds / 60_000))} min`;
  if (hours < 24) return `${hours} hr`;
  return `${Math.floor(hours / 24)} day`;
}

function ApplicationCard({ candidateId, application }: { candidateId: string; application: ApplicationSummary }) {
  return (
    <article className="panel application-card">
      <div className="panel-title">
        <div><p className="eyebrow">{application.company}</p><h3>{application.role}</h3></div>
        <StatusPill status={application.state} />
      </div>
      <dl className="compact-metadata">
        <div><dt>Score</dt><dd>{application.score ?? "Not scored"}</dd></div>
        <div><dt>Last event</dt><dd>{application.last_event?.replaceAll("_", " ") ?? "Created"}</dd></div>
        <div><dt>Age in state</dt><dd>{ageLabel(application.updated_at)}</dd></div>
      </dl>
      <p className="muted">Next: {application.next_action}</p>
      <Link className="button secondary" href={`/applications/${application.application_id}?candidate_id=${encodeURIComponent(candidateId)}`}>Open application</Link>
    </article>
  );
}

export function ApplicationPipeline({ candidateId, applications }: { candidateId: string; applications: ApplicationSummary[] }) {
  const [view, setView] = useState<"list" | "board">("list");
  if (!applications.length) return <div className="empty-state"><h2>No applications yet</h2><p>Generate materials from a scored job to create a controlled application.</p></div>;
  return (
    <section aria-labelledby="pipeline-view-heading">
      <div className="section-heading">
        <div><p className="eyebrow">Candidate-scoped workflow</p><h2 id="pipeline-view-heading">Application states</h2></div>
        <div className="view-toggle" aria-label="Pipeline view">
          <button type="button" className={view === "list" ? "button primary" : "button secondary"} aria-pressed={view === "list"} onClick={() => setView("list")}>List</button>
          <button type="button" className={view === "board" ? "button primary" : "button secondary"} aria-pressed={view === "board"} onClick={() => setView("board")}>Board</button>
        </div>
      </div>
      {view === "list" ? (
        <div className="pipeline-grid" aria-label="Application list">
          {applications.map((application) => <ApplicationCard candidateId={candidateId} application={application} key={application.application_id} />)}
        </div>
      ) : (
        <div className="pipeline-board" aria-label="Application board">
          {lanes.map((lane) => {
            const items = applications.filter((application) => lane.states.includes(application.state));
            return (
              <section className="pipeline-lane" aria-label={lane.label} key={lane.label}>
                <h3>{lane.label} <span className="muted">({items.length})</span></h3>
                {items.map((application) => <ApplicationCard candidateId={candidateId} application={application} key={application.application_id} />)}
                {!items.length ? <p className="muted">No applications</p> : null}
              </section>
            );
          })}
        </div>
      )}
    </section>
  );
}
