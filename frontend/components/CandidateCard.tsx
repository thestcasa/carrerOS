"use client";

import Link from "next/link";
import { selectActiveCandidate } from "@/lib/active-candidate";
import type { CandidateSummary } from "@/lib/types";
import { StatusPill } from "./StatusPill";

export function CandidateCard({ candidate }: { candidate: CandidateSummary }) {
  const valid = candidate.configuration_status === "valid";
  return (
    <article className="candidate-card">
      <div className="candidate-avatar" aria-hidden="true">
        {candidate.display_name.slice(0, 2).toUpperCase()}
      </div>
      <div className="candidate-card-body">
        <div className="candidate-title-row">
          <div>
            <p className="eyebrow">Candidate profile</p>
            <h2>{candidate.display_name}</h2>
          </div>
          <StatusPill status={valid ? "valid" : "invalid"} />
        </div>
        <dl className="metadata-list">
          <div><dt>ID</dt><dd>{candidate.candidate_id}</dd></div>
          <div><dt>Version</dt><dd>{candidate.profile_version ?? "Unavailable"}</dd></div>
          <div><dt>Submission automation</dt><dd>{candidate.automation_status}</dd></div>
        </dl>
        <div className="card-actions">
          <Link onClick={() => selectActiveCandidate(candidate.candidate_id)} className="button primary" href={`/candidates/${candidate.candidate_id}/readiness`}>
            Review readiness
          </Link>
          <Link onClick={() => selectActiveCandidate(candidate.candidate_id)} className="button secondary" href={`/candidates/${candidate.candidate_id}/profile`}>
            Edit profile
          </Link>
        </div>
      </div>
    </article>
  );
}
