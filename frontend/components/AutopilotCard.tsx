import Link from "next/link";
import type { ApplicationSummary, DiscoverySourceView, HumanActionView, JobSummary, SettingsView } from "@/lib/types";
import { automationStatus } from "@/lib/product-semantics";
import { ProductIcon } from "./ProductIcon";

function scanLabel(sources: DiscoverySourceView[], field: "last_success_at" | "next_run_at") {
  const values = sources.map((source) => source[field]).filter((value): value is string => Boolean(value)).sort();
  const value = field === "last_success_at" ? values.at(-1) : values[0];
  if (!value) return field === "last_success_at" ? "No scan recorded" : "Not scheduled";
  return new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export function AutopilotCard({ candidateId, settings, actions, jobs, applications, sources }: {
  candidateId: string; settings: SettingsView; actions: HumanActionView[]; jobs: JobSummary[];
  applications: ApplicationSummary[]; sources: DiscoverySourceView[];
}) {
  const pending = actions.filter((action) => action.status === "pending").length;
  const status = automationStatus(settings, pending);
  const activeSources = sources.filter((source) => source.enabled).length;
  const shortlisted = jobs.filter((job) => job.state === "shortlisted").length;
  const prepared = applications.filter((application) => !["discovered", "skipped", "withdrawn"].includes(application.state)).length;
  return (
    <article className={`autopilot-card semantic-${status.tone}`} aria-labelledby="autopilot-heading">
      <div className="autopilot-card-head">
        <div><p className="card-kicker">Autopilot</p><h2 id="autopilot-heading">{status.label}</h2></div>
        <span className={`status-dot semantic-${status.tone}`} aria-hidden="true" />
      </div>
      <p>{status.description}</p>
      {settings.emergency_stopped ? <p className="autopilot-warning"><ProductIcon name="shield" /> Emergency stop is enabled. Career OS cannot authorize new applications.</p> : null}
      <dl className="autopilot-metrics">
        <div><dt>Sources</dt><dd>{activeSources} active</dd></div>
        <div><dt>Jobs found</dt><dd>{jobs.length}</dd></div>
        <div><dt>Shortlisted</dt><dd>{shortlisted}</dd></div>
        <div><dt>Prepared</dt><dd>{prepared}</dd></div>
      </dl>
      <div className="autopilot-scan">
        <span><ProductIcon name="clock" /> Last scan</span><strong>{scanLabel(sources, "last_success_at")}</strong>
        <span>Next scan</span><strong>{scanLabel(sources, "next_run_at")}</strong>
      </div>
      <Link className="card-link" href={`/settings?candidate_id=${encodeURIComponent(candidateId)}`}>Manage Autopilot <ProductIcon name="chevron" /></Link>
    </article>
  );
}
