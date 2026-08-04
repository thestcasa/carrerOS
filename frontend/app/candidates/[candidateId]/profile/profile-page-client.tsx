"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ErrorState, LoadingState } from "@/components/LoadingState";
import { ProfileEditor } from "@/components/ProfileEditor";
import { api } from "@/lib/api";
import type { CandidateDetail, EditableSection } from "@/lib/types";

export function ProfilePageClient({ candidateId, initialSection }: { candidateId: string; initialSection?: EditableSection }) {
  const [detail, setDetail] = useState<CandidateDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try { setDetail(await api.candidate(candidateId)); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "The candidate profile is unavailable."); }
  }
  useEffect(() => {
    let active = true;
    api.candidate(candidateId)
      .then((candidateDetail) => { if (active) setDetail(candidateDetail); })
      .catch((requestError: unknown) => { if (active) setError(requestError instanceof Error ? requestError.message : "The candidate profile is unavailable."); });
    return () => { active = false; };
  }, [candidateId]);

  return (
    <div className="page-wrap wide-page">
      <header className="page-header profile-page-header">
        <div><p className="eyebrow">{candidateId}</p><h1>Core profile editor</h1></div>
        <Link className="button secondary" href={`/candidates/${candidateId}/readiness`}>View readiness</Link>
      </header>
      {error ? <ErrorState message={error} retry={() => void load()} /> : null}
      {!error && !detail ? <LoadingState label="Loading versioned profile" /> : null}
      {detail ? <ProfileEditor detail={detail} initialSection={initialSection} /> : null}
    </div>
  );
}
