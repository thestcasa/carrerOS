"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, api } from "@/lib/api";
import type { AtsPlatform, DiscoveryResult, DiscoverySourceView, JsonObject } from "@/lib/types";

function idempotencyKey() {
  return globalThis.crypto?.randomUUID?.() ?? `discovery-${Date.now()}`;
}

export function DiscoveryControls({
  candidateId,
  onComplete,
}: {
  candidateId: string;
  onComplete: (result: DiscoveryResult) => void;
}) {
  const [platform, setPlatform] = useState<AtsPlatform>("greenhouse");
  const [company, setCompany] = useState("");
  const [companyDomain, setCompanyDomain] = useState("");
  const [payloadText, setPayloadText] = useState("[]");
  const [boardToken, setBoardToken] = useState("");
  const [cadenceMinutes, setCadenceMinutes] = useState(60);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sources, setSources] = useState<DiscoverySourceView[] | null>(null);

  useEffect(() => {
    let active = true;
    api.discoverySources(candidateId).then((result) => { if (active) setSources(result); }).catch(() => { if (active) setSources([]); });
    return () => { active = false; };
  }, [candidateId]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    let payloads: JsonObject[];
    try {
      const parsed: unknown = JSON.parse(payloadText);
      if (!Array.isArray(parsed) || parsed.some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
        throw new Error("Payload must be a JSON array of ATS job objects.");
      }
      payloads = parsed as JsonObject[];
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Payload is not valid JSON.");
      return;
    }
    if (payloads.length === 0) {
      setError("Add at least one fixture or provider payload before discovery.");
      return;
    }
    setBusy(true);
    try {
      const result = await api.discoverJobs(
        { candidate_id: candidateId, platform, company, company_domain: companyDomain, payloads },
        idempotencyKey(),
      );
      setMessage(`${result.discovered} new or changed; ${result.unchanged} unchanged.`);
      onComplete(result);
    } catch (reason) {
      setError(reason instanceof ApiError ? `${reason.code}: ${reason.message}` : "Discovery failed safely.");
    } finally {
      setBusy(false);
    }
  }

  async function schedule() {
    setBusy(true); setError(null);
    try {
      await api.createDiscoverySource(candidateId, { provider: platform, company, company_domain: companyDomain, board_token: boardToken, cadence_minutes: cadenceMinutes, enabled: true }, idempotencyKey());
      setSources(await api.discoverySources(candidateId));
    } catch (reason) { setError(reason instanceof ApiError ? `${reason.code}: ${reason.message}` : "Source configuration failed safely."); } finally { setBusy(false); }
  }

  async function toggleSource(source: DiscoverySourceView) {
    setBusy(true); setError(null);
    try { await api.updateDiscoverySource(candidateId, source.source_id, { enabled: !source.enabled }, idempotencyKey()); setSources(await api.discoverySources(candidateId)); } catch (reason) { setError(reason instanceof Error ? reason.message : "Source update failed safely."); } finally { setBusy(false); }
  }

  return (
    <section className="panel discovery-controls" aria-labelledby="discovery-controls-heading">
      <div className="panel-title">
        <div>
          <p className="eyebrow">Source controls</p>
          <h2 id="discovery-controls-heading">Run discovery</h2>
        </div>
        <span className="status-text" role="status">{busy ? "Discovery running" : message ? "Last run completed" : "Ready"}</span>
      </div>
      <h3>Scheduled sources</h3>
      {sources === null ? <p className="muted">Loading discovery schedule…</p> : sources.length === 0 ? <p className="muted">No scheduled ATS sources configured.</p> : <ul className="blocker-list">{sources.map((source) => <li key={source.source_id}><strong>{source.company}</strong> · {source.provider} · every {source.cadence_minutes} minutes · {source.enabled ? source.last_status ?? "not run" : "paused"} · {source.last_discovered} changed / {source.last_unchanged} unchanged · next {source.next_run_at}{source.last_error ? ` · ${source.last_error}` : ""} <button className="text-button" type="button" disabled={busy} onClick={() => void toggleSource(source)}>{source.enabled ? "Pause source" : "Enable source"}</button></li>)}</ul>}
      <h3>Manual fixture import</h3>
      <p className="muted">Development-only structured payload import. Source text remains untrusted and cannot trigger submission.</p>
      <form onSubmit={submit}>
        <div className="field-grid">
          <label className="form-field"><span>ATS platform</span><select value={platform} onChange={(event) => setPlatform(event.target.value as AtsPlatform)}><option value="greenhouse">Greenhouse</option><option value="lever">Lever</option><option value="ashby">Ashby</option></select></label>
          <label className="form-field"><span>Company</span><input required value={company} onChange={(event) => setCompany(event.target.value)} /></label>
          <label className="form-field"><span>Official company domain</span><input required inputMode="url" placeholder="example.invalid" value={companyDomain} onChange={(event) => setCompanyDomain(event.target.value)} /></label>
          <label className="form-field"><span>Public board token</span><input value={boardToken} onChange={(event) => setBoardToken(event.target.value)} /></label>
          <label className="form-field"><span>Cadence minutes</span><input type="number" min={15} max={1440} value={cadenceMinutes} onChange={(event) => setCadenceMinutes(Number(event.target.value))} /></label>
          <label className="form-field"><span>Structured payloads</span><textarea required rows={5} spellCheck={false} value={payloadText} onChange={(event) => setPayloadText(event.target.value)} aria-describedby="payload-help" /><small id="payload-help">JSON array from an approved adapter or deterministic fixture.</small></label>
        </div>
        {error ? <p className="form-message error" role="alert">{error}</p> : null}
        {message ? <p className="form-message success" role="status">{message}</p> : null}
        <div className="editor-actions"><button className="button secondary" type="button" disabled={busy || !company || !companyDomain || !boardToken} onClick={() => void schedule()}>Schedule source</button><button className="button primary" type="submit" disabled={busy}>{busy ? "Discovering…" : "Run discovery"}</button></div>
      </form>
    </section>
  );
}
