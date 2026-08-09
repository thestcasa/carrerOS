"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ErrorState, LoadingState } from "@/components/LoadingState";
import { GuidedPipeline } from "@/components/GuidedPipeline";
import { StatusPill } from "@/components/StatusPill";
import { api } from "@/lib/api";
import { useActiveCandidateId } from "@/lib/active-candidate";
import type { AnalyticsOverview, ApplicationSummary, CandidateSummary, HealthReport, HumanActionView, JobSummary, NotificationView, ReadinessReport, SettingsView } from "@/lib/types";

export default function OverviewPage() {
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [candidates, setCandidates] = useState<CandidateSummary[] | null>(null);
  const [error, setError] = useState<{ candidateId: string; message: string } | null>(null);
  const [analytics, setAnalytics] = useState<AnalyticsOverview | null>(null);
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [actions, setActions] = useState<HumanActionView[] | null>(null);
  const [readiness, setReadiness] = useState<ReadinessReport | null>(null);
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [applications, setApplications] = useState<ApplicationSummary[] | null>(null);
  const [notifications, setNotifications] = useState<NotificationView[] | null>(null);
  const [loadedCandidateId, setLoadedCandidateId] = useState<string | null>(null);
  const requestGeneration = useRef(0);
  const activeCandidate = useActiveCandidateId();

  const load = useCallback(async (candidateId: string, generation: number) => {
    try {
      const [healthReport, candidateList, analyticsReport, settingsReport, humanActions, readinessReport, jobList, applicationList, notificationList] = await Promise.all([api.health(), api.candidates(), api.analytics(candidateId), api.settings(candidateId), api.humanActions(candidateId), api.readiness(candidateId), api.jobs(candidateId), api.applications(candidateId), api.notifications(candidateId)]);
      if (generation !== requestGeneration.current) return;
      setError(null);
      setHealth(healthReport);
      setCandidates(candidateList);
      setAnalytics(analyticsReport); setSettings(settingsReport); setActions(humanActions);
      setReadiness(readinessReport); setJobs(jobList); setApplications(applicationList);
      setNotifications(notificationList);
      setLoadedCandidateId(candidateId);
    } catch (requestError) {
      if (generation !== requestGeneration.current) return;
      setAnalytics(null); setSettings(null); setActions(null); setReadiness(null); setJobs(null); setApplications(null); setNotifications(null); setLoadedCandidateId(null);
      setError({ candidateId, message: requestError instanceof Error ? requestError.message : "The control plane is unavailable." });
    }
  }, []);

  useEffect(() => {
    if (!activeCandidate) return;
    const generation = ++requestGeneration.current;
    void Promise.resolve().then(() => load(activeCandidate, generation));
    return () => {
      if (requestGeneration.current === generation) requestGeneration.current += 1;
    };
  }, [activeCandidate, load]);

  useEffect(() => {
    if (!activeCandidate) return;
    const interval = globalThis.setInterval(() => {
      void load(activeCandidate, ++requestGeneration.current);
    }, 15_000);
    return () => globalThis.clearInterval(interval);
  }, [activeCandidate, load]);

  if (!activeCandidate) return null;

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
          <div className="control-row">
            <span>Live submission</span>
            <StatusPill
              status={
                settings?.controlled_submission_enabled ? "READY_WITH_WARNINGS" : "BLOCKED"
              }
            />
          </div>
        </div>
      </section>

      {error?.candidateId === activeCandidate ? <ErrorState message={error.message} retry={() => void load(activeCandidate, ++requestGeneration.current)} /> : null}
      {error?.candidateId !== activeCandidate && (!health || !candidates || loadedCandidateId !== activeCandidate || !analytics || !settings || !actions || !readiness || !jobs || !applications || !notifications) ? <LoadingState label="Checking the control plane" /> : null}

      {health && candidates && loadedCandidateId === activeCandidate && analytics && settings && actions && readiness && jobs && applications && notifications ? (
        <>
        <GuidedPipeline candidateId={activeCandidate} readiness={readiness} jobs={jobs} applications={applications} actions={actions} />
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
            <p className="eyebrow">Automation</p>
            <h2>{settings.automation_mode.replaceAll("_", " ")}</h2>
            <p>{settings.autonomy_blockers.length ? `${settings.autonomy_blockers.length} blockers prevent autonomous mode.` : "Autonomy prerequisites are recorded."}</p>
            <Link href={`/settings?candidate_id=${encodeURIComponent(activeCandidate)}`}>Open safety settings →</Link>
          </article>
          <article className="panel metric-panel"><span className="large-metric">{analytics.applications}</span><h2>Applications</h2><p>{analytics.confirmations} backend-confirmed.</p></article>
          <article className="panel metric-panel"><span className="large-metric">{actions.filter((action) => action.status === "pending").length}</span><h2>Human actions</h2><Link href={`/actions?candidate_id=${encodeURIComponent(activeCandidate)}`}>Open intervention queue →</Link></article>
          <article className="panel metric-panel"><span className="large-metric">{analytics.security_events_unresolved}</span><h2>Security findings</h2><Link href={`/security?candidate_id=${encodeURIComponent(activeCandidate)}`}>Review security ledger →</Link></article>
          <article className="panel activity-panel">
            <p className="eyebrow">Near-real-time activity</p>
            <h2>Recent events</h2>
            {[...notifications]
              .sort((left, right) => right.created_at.localeCompare(left.created_at))
              .slice(0, 5)
              .map((notification) => (
                <div className="activity-row" key={notification.notification_id}>
                  <strong>{notification.event_type.replaceAll("_", " ")}</strong>
                  <span>{notification.message}</span>
                  <small>{new Date(notification.created_at).toLocaleString()}</small>
                </div>
              ))}
            {!notifications.length ? <p className="muted">No recent notifications. This view refreshes every 15 seconds.</p> : null}
          </article>
        </section>
        </>
      ) : null}
    </div>
  );
}
