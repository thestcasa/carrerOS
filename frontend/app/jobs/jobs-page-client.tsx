"use client";

import { useEffect, useState } from "react";
import { JobsInbox } from "@/components/JobsInbox";
import { DiscoveryControls } from "@/components/DiscoveryControls";
import { ErrorState, LoadingState } from "@/components/LoadingState";
import { api } from "@/lib/api";
import type { JobSummary } from "@/lib/types";

export function JobsPageClient({ candidateId }: { candidateId: string }) {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    api.jobs(candidateId)
      .then((data) => { if (active) setJobs(data); })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Jobs are unavailable.");
      });
    return () => { active = false; };
  }, [candidateId, reload]);
  return (
    <div className="page-wrap wide-page">
      <header className="page-header">
        <div><p className="eyebrow">Recommended for you</p><h1>Find your next job</h1></div>
        <p>Compare opportunities, prepare a tailored application, or continue manually on the employer&apos;s official website.</p>
      </header>
      <details className="advanced-diagnostics jobs-advanced-controls">
        <summary>Advanced: job sources and discovery</summary>
        <DiscoveryControls candidateId={candidateId} onComplete={() => setReload((value) => value + 1)} />
      </details>
      {error ? <ErrorState message={error} /> : null}
      {!error && !jobs ? <LoadingState label="Loading jobs" /> : null}
      {jobs ? <JobsInbox candidateId={candidateId} jobs={jobs} /> : null}
    </div>
  );
}
