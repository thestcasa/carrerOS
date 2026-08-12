"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ErrorState, LoadingState } from "@/components/LoadingState";
import { ProfileOverview } from "@/components/ProfileOverview";
import { CVImportPanel } from "@/components/CVImportPanel";
import { ProfileEditor } from "@/components/ProfileEditor";
import { api } from "@/lib/api";
import { selectActiveCandidate } from "@/lib/active-candidate";
import type { CandidateDetail, EditableSection } from "@/lib/types";

export function ProfilePageClient({ candidateId, initialSection }: { candidateId: string; initialSection?: EditableSection }) {
  const [detail, setDetail] = useState<CandidateDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      const candidateDetail = await api.candidate(candidateId);
      selectActiveCandidate(candidateId);
      setDetail(candidateDetail);
    }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "The candidate profile is unavailable."); }
  }
  useEffect(() => {
    let active = true;
    api.candidate(candidateId)
      .then((candidateDetail) => {
        if (!active) return;
        selectActiveCandidate(candidateId);
        setDetail(candidateDetail);
      })
      .catch((requestError: unknown) => { if (active) setError(requestError instanceof Error ? requestError.message : "The candidate profile is unavailable."); });
    return () => { active = false; };
  }, [candidateId]);

  return (
    <div className="page-wrap wide-page">
      <header className="page-header profile-page-header">
        <div><p className="eyebrow">Your profile</p><h1>Profile</h1><p>Keep the facts used in every application accurate and under your control.</p></div>
        <Link className="button secondary" href={`/candidates/${candidateId}/readiness`}>Check profile status</Link>
      </header>
      {detail ? <ProfileOverview detail={detail} /> : null}
      {error ? <ErrorState message={error} retry={() => void load()} /> : null}
      {!error && !detail ? <LoadingState label="Loading versioned profile" /> : null}
      {detail ? <CVImportPanel candidateId={candidateId} onApplied={setDetail} /> : null}
      {detail ? <details id="profile-editor" className="advanced-diagnostics profile-details" open={Boolean(initialSection)}><summary>Review and edit profile details</summary><ProfileEditor key={initialSection ?? "identity"} detail={detail} initialSection={initialSection} /></details> : null}
    </div>
  );
}
