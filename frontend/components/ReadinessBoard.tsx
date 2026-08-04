import Link from "next/link";
import type { ReadinessReport } from "@/lib/types";
import { StatusPill } from "./StatusPill";

const editorSections = new Set([
  "identity",
  "biography",
  "career_strategy",
  "preferences",
  "legal_status",
]);

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
            const editable = editorSections.has(domain.field_path);
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
                    <Link href={`/candidates/${candidateId}/profile?section=${domain.field_path}`}>
                      Edit domain <span aria-hidden="true">→</span>
                    </Link>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
}
