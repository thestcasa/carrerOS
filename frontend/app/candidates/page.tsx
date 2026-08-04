"use client";

import { useEffect, useState } from "react";
import { CandidateCard } from "@/components/CandidateCard";
import { ErrorState, LoadingState } from "@/components/LoadingState";
import { api } from "@/lib/api";
import type { CandidateSummary } from "@/lib/types";

export default function CandidatesPage() {
  const [candidates, setCandidates] = useState<CandidateSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try { setCandidates(await api.candidates()); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "Candidate profiles are unavailable."); }
  }

  useEffect(() => {
    let active = true;
    api.candidates()
      .then((candidateList) => { if (active) setCandidates(candidateList); })
      .catch((requestError: unknown) => { if (active) setError(requestError instanceof Error ? requestError.message : "Candidate profiles are unavailable."); });
    return () => { active = false; };
  }, []);

  return (
    <div className="page-wrap narrow-page">
      <header className="page-header">
        <div><p className="eyebrow">Candidate boundary</p><h1>Select a candidate</h1></div>
        <p>Every workflow, score, answer, and archive remains isolated by candidate ID.</p>
      </header>
      {error ? <ErrorState message={error} retry={() => void load()} /> : null}
      {!error && candidates === null ? <LoadingState label="Loading candidates" /> : null}
      {candidates?.length === 0 ? <div className="empty-state"><h2>No candidate configuration found</h2><p>Add a versioned profile under <code>candidates/&lbrace;candidate_id&rbrace;/</code>.</p></div> : null}
      <div className="candidate-list">{candidates?.map((candidate) => <CandidateCard candidate={candidate} key={candidate.candidate_id} />)}</div>
    </div>
  );
}
