"use client";

import { useEffect, useState } from "react";
import { ApplicationPipeline } from "@/components/ApplicationPipeline";
import { ErrorState, LoadingState } from "@/components/LoadingState";
import { api } from "@/lib/api";
import type { ApplicationSummary } from "@/lib/types";

export function ApplicationsPageClient({ candidateId }: { candidateId: string }) {
  const [applications, setApplications] = useState<ApplicationSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { let active = true; api.applications(candidateId).then((items) => { if (active) setApplications(items); }).catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Applications are unavailable."); }); return () => { active = false; }; }, [candidateId]);
  return <div className="page-wrap wide-page"><header className="page-header"><div><p className="eyebrow">{candidateId}</p><h1>Application pipeline</h1></div><p>Every transition, material version, answer, archive, and confirmation remains candidate-scoped and auditable.</p></header>{error ? <ErrorState message={error} /> : null}{!error && !applications ? <LoadingState label="Loading application pipeline" /> : null}{applications ? <ApplicationPipeline candidateId={candidateId} applications={applications} /> : null}</div>;
}
