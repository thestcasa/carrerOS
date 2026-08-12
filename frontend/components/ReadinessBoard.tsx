import Link from "next/link";
import type { ReadinessReport } from "@/lib/types";
import { StatusPill } from "./StatusPill";

const editorSections = new Set([
  "candidate_controls",
  "identity",
  "biography",
  "education",
  "experience",
  "projects",
  "skills",
  "languages",
  "career_strategy",
  "scoring_rules",
  "preferences",
  "legal_status",
  "approved_answers",
  "cv_rules",
  "cover_letter_rules",
  "companies",
  "roles",
  "certifications",
  "publications",
  "notification_rules",
]);

function editorSection(fieldPath: string): string | null {
  const root = fieldPath.split(".")[0];
  if (root === "manifest") return "candidate_controls";
  return editorSections.has(root) ? root : null;
}

function blockerLabel(blocker: string) {
  return blocker.replaceAll("_", " ");
}

export function ReadinessBoard({
  candidateId,
  report,
}: {
  candidateId: string;
  report: ReadinessReport;
}) {
  return (
    <div className="readiness-layout">
      <section aria-labelledby="capability-heading">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Operational controls</p>
            <h2 id="capability-heading">Capability readiness</h2>
          </div>
          <p>Each capability is assessed independently. A blocked capability cannot run.</p>
        </div>
        <div className="capability-grid">
          {report.capabilities.map((capability) => (
            <article className="capability-card" key={capability.capability}>
              <StatusPill status={capability.status} />
              <h3>{capability.label}</h3>
              {capability.blockers.length ? (
                <ul className="blocker-list">
                  {capability.blockers.map((blocker) => <li key={blocker}>{blockerLabel(blocker)}</li>)}
                </ul>
              ) : (
                <p className="muted">All required profile domains are configured.</p>
              )}
            </article>
          ))}
        </div>
      </section>

      <section aria-labelledby="domain-heading">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Source configuration</p>
            <h2 id="domain-heading">Profile domains</h2>
          </div>
          <p>Open an editable domain to resolve its configuration blockers.</p>
        </div>
        <div className="domain-list">
          {report.domains.map((domain) => {
            const editable = editorSection(domain.field_path);
            return (
              <article className="domain-row" key={domain.domain}>
                <div>
                  <h3>{domain.label}</h3>
                  <p className="field-path">{domain.field_path}</p>
                  {domain.issues.map((issue) => <p className="issue-text" key={issue.code}>{issue.message}</p>)}
                </div>
                <div className="domain-action">
                  <StatusPill status={domain.status} />
                  {editable ? (
                    <Link href={`/candidates/${candidateId}/profile?section=${editable}`}>
                      Edit domain <span aria-hidden="true">→</span>
                    </Link>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
      </section>
      <section className="panel action-panel" aria-label="Readiness next action">
        <div>
          <p className="eyebrow">Next safe action</p>
          <h2>{report.status === "ready" ? "Choose a job to review" : "Resolve the first blocker"}</h2>
          <p>
            {report.status === "ready"
              ? "Your candidate package is ready for discovery, scoring, and material preparation."
              : "Open the first blocked profile domain. Career OS will recalculate readiness after the saved version is validated."}
          </p>
        </div>
        {report.status === "ready" ? (
          <Link
            className="button primary"
            href={`/jobs?candidate_id=${encodeURIComponent(candidateId)}`}
          >
            Browse jobs
          </Link>
        ) : (
          <Link
            className="button primary"
            href={`/candidates/${candidateId}/profile?section=${encodeURIComponent(
              editorSection(
                report.domains.find((domain) =>
                  ["BLOCKED", "NOT_CONFIGURED"].includes(domain.status),
                )?.field_path ?? "identity",
              ) ?? "identity",
            )}`}
          >
            Edit candidate profile
          </Link>
        )}
      </section>
    </div>
  );
}
