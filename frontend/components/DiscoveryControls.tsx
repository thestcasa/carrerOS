"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { ApiError, api } from "@/lib/api";
import type { AtsPlatform, DiscoveryResult, JsonObject } from "@/lib/types";

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
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  return (
    <section className="panel discovery-controls" aria-labelledby="discovery-controls-heading">
      <div className="panel-title">
        <div>
          <p className="eyebrow">Source controls</p>
          <h2 id="discovery-controls-heading">Run discovery</h2>
        </div>
        <span className="status-text" role="status">{busy ? "Discovery running" : message ? "Last run completed" : "Ready"}</span>
      </div>
      <p className="muted">Import structured ATS payloads. Source text remains untrusted and cannot trigger submission.</p>
      <form onSubmit={submit}>
        <div className="field-grid">
          <label className="form-field"><span>ATS platform</span><select value={platform} onChange={(event) => setPlatform(event.target.value as AtsPlatform)}><option value="greenhouse">Greenhouse</option><option value="lever">Lever</option><option value="ashby">Ashby</option></select></label>
          <label className="form-field"><span>Company</span><input required value={company} onChange={(event) => setCompany(event.target.value)} /></label>
          <label className="form-field"><span>Official company domain</span><input required inputMode="url" placeholder="example.invalid" value={companyDomain} onChange={(event) => setCompanyDomain(event.target.value)} /></label>
          <label className="form-field"><span>Structured payloads</span><textarea required rows={5} spellCheck={false} value={payloadText} onChange={(event) => setPayloadText(event.target.value)} aria-describedby="payload-help" /><small id="payload-help">JSON array from an approved adapter or deterministic fixture.</small></label>
        </div>
        {error ? <p className="form-message error" role="alert">{error}</p> : null}
        {message ? <p className="form-message success" role="status">{message}</p> : null}
        <div className="editor-actions"><button className="button primary" type="submit" disabled={busy}>{busy ? "Discovering…" : "Run discovery"}</button></div>
      </form>
    </section>
  );
}
