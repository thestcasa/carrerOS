"use client";

import { useCallback, useEffect, useState } from "react";
import { ErrorState, LoadingState } from "@/components/LoadingState";
import { StatusPill } from "@/components/StatusPill";
import { api } from "@/lib/api";
import type { SecurityEventView } from "@/lib/types";

export function SecurityPageClient({ candidateId }: { candidateId: string }) {
  const [events, setEvents] = useState<SecurityEventView[] | null>(null); const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.securityEvents(candidateId).then(setEvents), [candidateId]); useEffect(() => { load().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Security events are unavailable.")); }, [load]);
  async function resolve(eventId: string) { try { await api.resolveSecurityEvent(candidateId, eventId); await load(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Resolution failed."); } }
  return <div className="page-wrap"><header className="page-header"><div><p className="eyebrow">Trust boundary</p><h1>Security events</h1></div><p>External content remains untrusted. Findings are explainable without revealing credentials, cookies, or hidden prompts.</p></header>{error ? <ErrorState message={error} /> : null}{!events ? <LoadingState label="Loading security event ledger" /> : events.length === 0 ? <div className="empty-state"><h2>No security events</h2><p>Prompt injection, redirects, denied file access, and blocked submissions will appear here.</p></div> : <div className="candidate-list">{events.map((event) => <article className="panel" key={event.event_id}><div className="panel-title"><div><p className="eyebrow">{event.severity}</p><h2>{event.category.replaceAll("_", " ")}</h2></div><StatusPill status={event.resolved ? "READY" : "BLOCKED"} /></div><pre>{JSON.stringify(event.details, null, 2)}</pre>{!event.resolved ? <button className="button secondary" onClick={() => void resolve(event.event_id)}>Resolve event</button> : null}</article>)}</div>}</div>;
}
