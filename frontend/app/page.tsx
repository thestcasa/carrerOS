"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ErrorState, LoadingState } from "@/components/LoadingState";
import { StatusPill } from "@/components/StatusPill";
import { api } from "@/lib/api";
import type { CandidateSummary, HealthReport } from "@/lib/types";

export default function OverviewPage() {
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [candidates, setCandidates] = useState<CandidateSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      const [healthReport, candidateList] = await Promise.all([api.health(), api.candidates()]);
      setHealth(healthReport);
      setCandidates(candidateList);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "The control plane is unavailable.");
    }
  }

  useEffect(() => {
    let active = true;
    Promise.all([api.health(), api.candidates()])
      .then(([healthReport, candidateList]) => {
        if (!active) return;
        setHealth(healthReport);
        setCandidates(candidateList);
      })
      .catch((requestError: unknown) => {
        if (active) setError(requestError instanceof Error ? requestError.message : "The control plane is unavailable.");
      });
    return () => { active = false; };
  }, []);

  return (
    <div className="page-wrap">
      <section className="hero">
        <div>
          <p className="eyebrow">Candidate-controlled application platform</p>
          <h1>Decisions stay explainable.<br />Submission stays deterministic.</h1>
          <p className="hero-copy">Career OS keeps candidate evidence, preferences, legal declarations, and automation permissions in versioned configuration.</p>
          <div className="hero-actions">
            <Link className="button primary" href="/candidates">Select a candidate</Link>
            <a className="button secondary" href="#system-status">View system status</a>
          </div>
        </div>
        <div className="control-card">
          <p className="eyebrow">Hard safety boundary</p>
          <strong>SubmissionGate defaults to deny</strong>
          <p>Only the deterministic gate may issue submission authorization. LLM workers and browser automation cannot override it.</p>
          <div className="control-row"><span>Live submission</span><StatusPill status="BLOCKED" /></div>
        </div>
      </section>

      {error ? <ErrorState message={error} retry={() => void load()} /> : null}
      {!error && (!health || !candidates) ? <LoadingState label="Checking the control plane" /> : null}

      {health && candidates ? (
        <section id="system-status" className="overview-grid">
          <article className="panel status-panel">
            <div className="panel-title"><div><p className="eyebrow">Runtime</p><h2>System status</h2></div><StatusPill status={health.status} /></div>
            <div className="service-list">
              {(["api", "database", "redis"] as const).map((name) => {
                const service = health[name];
                return <div key={name}><span>{name}</span><span>{service.status === "available" ? "Available" : service.detail ?? "Unavailable"}</span></div>;
              })}
            </div>
          </article>
          <article className="panel metric-panel">
            <p className="eyebrow">Configuration</p>
            <span className="large-metric">{candidates.length}</span>
            <h2>Candidate profile{candidates.length === 1 ? "" : "s"}</h2>
            <p>{candidates.filter((candidate) => candidate.configuration_status === "valid").length} valid configuration{candidates.length === 1 ? "" : "s"} available.</p>
          </article>
          <article className="panel next-panel">
            <p className="eyebrow">Current milestone</p>
            <h2>Profile and readiness</h2>
            <p>Review versioned candidate data and see capability-specific blockers before any autonomous workflow is introduced.</p>
            <Link href="/candidates">Open candidate workspace →</Link>
          </article>
        </section>
      ) : null}
    </div>
  );
}
