"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { CandidateCard } from "@/components/CandidateCard";
import { ErrorState, LoadingState } from "@/components/LoadingState";
import { api } from "@/lib/api";
import type { CandidateSummary } from "@/lib/types";

export default function CandidatesPage() {
  const [candidates, setCandidates] = useState<CandidateSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [creating, setCreating] = useState(false);
  const createCommand = useRef<{ identity: string; key: string } | null>(null);

  const router = useRouter();
  async function load() {
    setError(null);
    try { setCandidates(await api.candidates()); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "Candidate profiles are unavailable."); }
  }

  async function createCandidate() {
    setCreating(true); setError(null);
    const baseId = displayName.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 48);
    const safeBaseId = /^[a-z]/.test(baseId) ? baseId : `candidate_${baseId || "profile"}`;
    const existingIds = new Set(candidates?.map((candidate) => candidate.candidate_id) ?? []);
    const candidateId = existingIds.has(safeBaseId) ? `${safeBaseId}_${Date.now().toString(36)}` : safeBaseId;
    const identity = JSON.stringify({ candidateId, displayName });
    if (createCommand.current?.identity !== identity) {
      createCommand.current = {
        identity,
        key: `create-candidate-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`,
      };
    }
    try {
      await api.createCandidate(candidateId, displayName, createCommand.current.key);
      createCommand.current = null;
      router.push(`/candidates/${candidateId}/profile`);
    }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "Candidate onboarding failed safely."); }
    finally { setCreating(false); }
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
        <div><p className="eyebrow">Your account</p><h1>Choose your profile</h1></div>
        <p>Continue with an existing profile or create one in a few steps.</p>
      </header>
      <section className="panel onboarding-panel"><div><p className="eyebrow">Get started</p><h2>Create your profile</h2><p>Enter your name, then upload your CV and review the information we find. Nothing is submitted without your approval.</p></div><label className="form-field"><span>Full name</span><input autoComplete="name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Your full name" /></label><button className="button primary" disabled={creating || !displayName.trim()} onClick={() => void createCandidate()}>{creating ? "Creating your profile..." : "Continue"}</button></section>
      {error ? <ErrorState message={error} retry={() => void load()} /> : null}
      {!error && candidates === null ? <LoadingState label="Loading candidates" /> : null}
      {candidates?.length === 0 ? <div className="empty-state"><h2>No profiles yet</h2><p>Create your first profile above.</p></div> : null}
      <div className="candidate-list">{candidates?.map((candidate) => <CandidateCard candidate={candidate} key={candidate.candidate_id} />)}</div>
    </div>
  );
}
