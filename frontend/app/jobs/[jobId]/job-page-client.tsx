"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { JobDetail } from "@/components/JobDetail";
import { ErrorState, LoadingState } from "@/components/LoadingState";
import { api } from "@/lib/api";
import type { JobDetail as JobDetailData } from "@/lib/types";

export function JobPageClient({ candidateId, jobId }: { candidateId: string; jobId: string }) {
  const router = useRouter();
  const [job, setJob] = useState<JobDetailData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<"verify" | "shortlist" | "skip" | "generate" | null>(null);
  const commandKeys = useRef(new Map<string, string>());
  async function runAction(action: "verify" | "shortlist" | "skip" | "generate") {
    setBusyAction(action);
    setActionError(null);
    const identity = `${candidateId}:${jobId}:${action}`;
    let key = commandKeys.current.get(identity);
    if (!key) {
      key = `${action}-${globalThis.crypto.randomUUID()}`;
      commandKeys.current.set(identity, key);
    }
    try {
      if (action === "generate") {
        const application = await api.generateMaterials(candidateId, jobId, key);
        commandKeys.current.delete(identity);
        router.push(`/applications/${application.application_id}?candidate_id=${encodeURIComponent(candidateId)}`);
        return;
      }
      const updated = action === "verify" ? await api.verifyJob(candidateId, jobId, key) : action === "shortlist" ? await api.shortlistJob(candidateId, jobId, key) : await api.skipJob(candidateId, jobId, key);
      commandKeys.current.delete(identity);
      setJob(updated);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "The action failed safely.");
    } finally {
      setBusyAction(null);
    }
  }
  useEffect(() => { let active = true; api.job(candidateId, jobId).then((data) => { if (active) setJob(data); }).catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Job analysis is unavailable."); }); return () => { active = false; }; }, [candidateId, jobId]);
  return <div className="page-wrap wide-page"><header className="page-header"><div><p className="eyebrow">{job?.company ?? candidateId}</p><h1>{job?.title ?? "Job analysis"}</h1></div><Link className="button secondary" href={`/jobs?candidate_id=${encodeURIComponent(candidateId)}`}>Back to inbox</Link></header>{error ? <ErrorState message={error} /> : null}{!error && !job ? <LoadingState label="Loading job evidence" /> : null}{job ? <JobDetail job={job} busyAction={busyAction} actionError={actionError} onAction={runAction} /> : null}</div>;
}
