"use client";

import { useEffect, useState } from "react";
import { ErrorState, LoadingState } from "@/components/LoadingState";
import { api } from "@/lib/api";
import type { AnalyticsOverview } from "@/lib/types";

export function AnalyticsPageClient({ candidateId }: { candidateId: string }) {
  const [overview, setOverview] = useState<AnalyticsOverview | null>(null); const [error, setError] = useState<string | null>(null); useEffect(() => { api.analytics(candidateId).then(setOverview).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Analytics are unavailable.")); }, [candidateId]);
  return <div className="page-wrap"><header className="page-header"><div><p className="eyebrow">{candidateId}</p><h1>Quality analytics</h1></div><p>Career OS optimizes for truthful, relevant applications and interviews—not raw volume.</p></header>{error ? <ErrorState message={error} /> : null}{!overview ? <LoadingState label="Loading candidate analytics" /> : <div className="analytics-grid"><article className="panel metric-panel"><span className="large-metric">{overview.applications}</span><h2>Applications</h2></article><article className="panel metric-panel"><span className="large-metric">{overview.average_score}</span><h2>Average score</h2></article><article className="panel metric-panel"><span className="large-metric">{overview.confirmations}</span><h2>Confirmed</h2></article><article className="panel"><p className="eyebrow">Pipeline</p><h2>By state</h2><dl className="metric-list">{Object.entries(overview.by_state).map(([label, value]) => <div key={label}><dt>{label.replaceAll("_", " ")}</dt><dd>{value}</dd></div>)}</dl></article><article className="panel"><p className="eyebrow">Strategy</p><h2>By role category</h2><dl className="metric-list">{Object.entries(overview.by_role_category).map(([label, value]) => <div key={label}><dt>{label.replaceAll("_", " ")}</dt><dd>{value}</dd></div>)}</dl></article><article className="panel"><p className="eyebrow">Intervention</p><h2>{overview.human_actions_pending} pending human actions</h2><p>{overview.security_events_unresolved} unresolved security events</p></article></div>}</div>;
}
