"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ErrorState, LoadingState } from "@/components/LoadingState";
import { ReadinessBoard } from "@/components/ReadinessBoard";
import { api } from "@/lib/api";
import type { ReadinessReport } from "@/lib/types";

export function ReadinessPageClient({ candidateId }: { candidateId: string }) {
  const [report, setReport] = useState<ReadinessReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try { setReport(await api.readiness(candidateId)); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "Readiness could not be calculated."); }
  }
  useEffect(() => {
    let active = true;
    api.readiness(candidateId)
      .then((readinessReport) => { if (active) setReport(readinessReport); })
      .catch((requestError: unknown) => { if (active) setError(requestError instanceof Error ? requestError.message : "Readiness could not be calculated."); });
    return () => { active = false; };
  }, [candidateId]);

  return (
    <div className="page-wrap wide-page">
      <header className="page-header readiness-header">
        <div><p className="eyebrow">{candidateId}</p><h1>Readiness by capability</h1><p>No aggregate percentage: each operating capability exposes its own deterministic blockers.</p></div>
        <Link className="button secondary" href={`/candidates/${candidateId}/profile`}>Edit core profile</Link>
      </header>
      {error ? <ErrorState message={error} retry={() => void load()} /> : null}
      {!error && !report ? <LoadingState label="Evaluating candidate configuration" /> : null}
      {report ? <ReadinessBoard candidateId={candidateId} report={report} /> : null}
    </div>
  );
}
