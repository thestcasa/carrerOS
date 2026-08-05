import Link from "next/link";
import { StatusPill } from "./StatusPill";
import type { ApplicationSummary } from "@/lib/types";

export function ApplicationPipeline({ candidateId, applications }: { candidateId: string; applications: ApplicationSummary[] }) {
  if (!applications.length) return <div className="empty-state"><h2>No applications yet</h2><p>Generate materials from a scored job to create a controlled application.</p></div>;
  return <div className="pipeline-grid">{applications.map((application) => (
    <article className="panel application-card" key={application.application_id}>
      <div className="panel-title"><div><p className="eyebrow">{application.company}</p><h2>{application.role}</h2></div><StatusPill status={application.state} /></div>
      <dl className="compact-metadata"><div><dt>Score</dt><dd>{application.score ?? "Not scored"}</dd></div><div><dt>Last event</dt><dd>{application.last_event?.replaceAll("_", " ") ?? "Created"}</dd></div></dl>
      <p className="muted">Next: {application.next_action}</p>
      <Link className="button secondary" href={`/applications/${application.application_id}?candidate_id=${encodeURIComponent(candidateId)}`}>Open application</Link>
    </article>
  ))}</div>;
}
