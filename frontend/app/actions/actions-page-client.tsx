"use client";

import { useCallback, useEffect, useState } from "react";
import { ErrorState, LoadingState } from "@/components/LoadingState";
import { StatusPill } from "@/components/StatusPill";
import { api } from "@/lib/api";
import type { HumanActionView } from "@/lib/types";

export function ActionsPageClient({ candidateId }: { candidateId: string }) {
  const [actions, setActions] = useState<HumanActionView[] | null>(null); const [error, setError] = useState<string | null>(null); const [busy, setBusy] = useState<string | null>(null);
  const load = useCallback(() => api.humanActions(candidateId).then(setActions), [candidateId]);
  useEffect(() => { load().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Human actions are unavailable.")); }, [load]);
  async function complete(actionId: string) { setBusy(actionId); setError(null); try { await api.completeHumanAction(candidateId, actionId, `complete-${crypto.randomUUID()}`); await load(); } catch (reason) { setError(reason instanceof Error ? reason.message : "The action could not be completed."); } finally { setBusy(null); } }
  return <div className="page-wrap"><header className="page-header"><div><p className="eyebrow">{candidateId}</p><h1>Human actions</h1></div><p>CAPTCHA, OTP, legal ambiguity, and novel sensitive questions pause in the same isolated browser session. Career OS never bypasses them.</p></header>{error ? <ErrorState message={error} /> : null}{!actions ? <LoadingState label="Loading human-action queue" /> : actions.length === 0 ? <div className="empty-state"><h2>No intervention required</h2><p>Paused workflows will appear here with an explicit reason and expiry.</p></div> : <div className="candidate-list">{actions.map((action) => <article className="panel" key={action.action_id}><div className="panel-title"><div><p className="eyebrow">{action.kind}</p><h2>{action.company} · {action.role}</h2></div><StatusPill status={action.status} /></div><p>{action.reason}</p><p className="muted">Created {new Date(action.created_at).toLocaleString()} · {action.expires_at ? `Expires ${new Date(action.expires_at).toLocaleString()}` : "No expiry"}</p>{action.status === "pending" ? <button className="button primary" disabled={busy === action.action_id} onClick={() => void complete(action.action_id)}>{busy === action.action_id ? "Checking…" : "Open browser session and mark complete"}</button> : null}</article>)}</div>}</div>;
}
