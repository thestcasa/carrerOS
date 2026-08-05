"use client";

import { useEffect, useRef, useState } from "react";
import { CandidateCard } from "@/components/CandidateCard";
import { ErrorState, LoadingState } from "@/components/LoadingState";
import { api } from "@/lib/api";
import type { CandidateSummary } from "@/lib/types";

export default function CandidatesPage() {
  const [candidates, setCandidates] = useState<CandidateSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [candidateId, setCandidateId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [creating, setCreating] = useState(false);
  const createCommand = useRef<{ identity: string; key: string } | null>(null);

  async function load() {
    setError(null);
    try { setCandidates(await api.candidates()); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "Candidate profiles are unavailable."); }
  }

  async function createCandidate() {
    setCreating(true); setError(null);
    const identity = JSON.stringify({ candidateId, displayName });
    if (createCommand.current?.identity !== identity) {
      createCommand.current = {
        identity,
        key: `create-candidate-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`,
      };
    }
    try { await api.createCandidate(candidateId, displayName, createCommand.current.key); createCommand.current = null; setCandidateId(""); setDisplayName(""); await load(); }
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
        <div><p className="eyebrow">Candidate boundary</p><h1>Select a candidate</h1></div>
        <p>Every workflow, score, answer, and archive remains isolated by candidate ID.</p>
      </header>
      <section className="panel onboarding-panel"><div><p className="eyebrow">Portable onboarding</p><h2>Create an unapproved candidate draft</h2><p>The new profile starts blocked. Replace fictional placeholders, validate every fact, then approve capabilities separately.</p></div><div className="field-grid"><label className="form-field"><span>Candidate ID</span><input value={candidateId} pattern="[a-z][a-z0-9_]{2,63}" onChange={(event) => setCandidateId(event.target.value)} /></label><label className="form-field"><span>Display name</span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></label></div><button className="button primary" disabled={creating || !candidateId || !displayName} onClick={() => void createCandidate()}>{creating ? "Creating…" : "Create blocked draft"}</button></section>
      {error ? <ErrorState message={error} retry={() => void load()} /> : null}
      {!error && candidates === null ? <LoadingState label="Loading candidates" /> : null}
      {candidates?.length === 0 ? <div className="empty-state"><h2>No candidate configuration found</h2><p>Add a versioned profile under <code>candidates/&lbrace;candidate_id&rbrace;/</code>.</p></div> : null}
      <div className="candidate-list">{candidates?.map((candidate) => <CandidateCard candidate={candidate} key={candidate.candidate_id} />)}</div>
    </div>
  );
}
