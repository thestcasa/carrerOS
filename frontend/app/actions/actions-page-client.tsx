"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ErrorState, LoadingState } from "@/components/LoadingState";
import { ProductIcon } from "@/components/ProductIcon";
import { StatusPill } from "@/components/StatusPill";
import { api } from "@/lib/api";
import type { HumanActionView } from "@/lib/types";

type ActionOperation = "open" | "complete" | "cancel";

export function ActionsPageClient({ candidateId }: { candidateId: string }) {
  const [actions, setActions] = useState<HumanActionView[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const commandKeys = useRef(new Map<string, string>());
  const load = useCallback(() => api.humanActions(candidateId).then(setActions), [candidateId]);

  useEffect(() => {
    load().catch((reason: unknown) =>
      setError(reason instanceof Error ? reason.message : "Human actions are unavailable."),
    );
  }, [load]);

  async function advance(action: HumanActionView, operation: ActionOperation) {
    setBusy(`${action.action_id}:${operation}`);
    setError(null);
    const identity = `${candidateId}:${action.action_id}:${operation}`;
    let key = commandKeys.current.get(identity);
    if (!key) {
      key = `${operation}-${globalThis.crypto.randomUUID()}`;
      commandKeys.current.set(identity, key);
    }
    try {
      if (operation === "open") {
        await api.openHumanSession(candidateId, action.action_id, key);
      } else if (operation === "complete") {
        await api.completeHumanAction(candidateId, action.action_id, key);
      } else {
        await api.cancelHumanAction(candidateId, action.action_id, key);
      }
      commandKeys.current.delete(identity);
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The action could not be advanced safely.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function downloadScreenshot(action: HumanActionView) {
    if (!action.screenshot_artifact_id) return;
    setBusy(`${action.action_id}:screenshot`);
    setError(null);
    try {
      const blob = await api.downloadArtifact(
        candidateId,
        action.application_id,
        action.screenshot_artifact_id,
      );
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `human-action-${action.action_id}-evidence.png`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "The screenshot could not be opened safely.",
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="page-wrap">
      <header className="page-header">
        <div><p className="eyebrow">Action required</p><h1>Needs your attention</h1></div>
        <p>Complete human-only steps so Career OS can continue safely. CAPTCHA and OTP are never bypassed.</p>
      </header>
      {error ? <ErrorState message={error} /> : null}
      {!actions ? (
        <LoadingState label="Loading human-action queue" />
      ) : actions.length === 0 ? (
        <div className="empty-state">
          <h2>No intervention required</h2>
          <p>Paused workflows will appear here with an explicit reason and expiry.</p>
        </div>
      ) : (
        <div className="candidate-list">
          {[...actions].sort((left, right) => Number(left.status !== "pending") - Number(right.status !== "pending") || left.created_at.localeCompare(right.created_at)).map((action) => {
            const actionBusy = busy?.startsWith(`${action.action_id}:`) ?? false;
            return (
              <article className="panel action-required-detail" key={action.action_id}>
                <div className="panel-title">
                  <div><p className="eyebrow">{action.kind}</p><h2>{action.company} · {action.role}</h2></div>
                  <StatusPill status={action.status} />
                </div>
                <p>{action.reason}</p>
                <p className="action-created"><ProductIcon name="clock" /> {new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(action.created_at))}</p>
                <details className="technical-inline"><summary>Technical details</summary>
                <dl className="metadata-list">
                  <div><dt>Safe origin</dt><dd>{action.safe_origin ?? "Unavailable"}</dd></div>
                  <div><dt>Browser session</dt><dd>{action.browser_session_health.replaceAll("_", " ")}</dd></div>
                  <div><dt>Interactive transport capability</dt><dd>{action.takeover_capability_status.replaceAll("_", " ")}</dd></div>
                  <div><dt>Local takeover handshake</dt><dd>{action.takeover_handshake_status.replaceAll("_", " ")}</dd></div>
                  <div><dt>Verifier</dt><dd>{action.verifier_state.replaceAll("_", " ")}</dd></div>
                  <div><dt>Created</dt><dd>{new Date(action.created_at).toLocaleString()}</dd></div>
                  <div><dt>Expiry</dt><dd>{action.expires_at ? new Date(action.expires_at).toLocaleString() : "No expiry"}</dd></div>
                  {action.screenshot_artifact_id ? (
                    <>
                      <div><dt>Screenshot artifact</dt><dd>{action.screenshot_artifact_id}</dd></div>
                      <div><dt>Screenshot SHA-256</dt><dd><code>{action.screenshot_sha256}</code></dd></div>
                    </>
                  ) : null}
                </dl>
                </details>
                <section aria-label="Action consequences">
                  <h3>Before continuing</h3>
                  <p>{action.continue_consequence}</p>
                  <p>{action.cancel_consequence}</p>
                </section>
                <div className="editor-actions">
                  {action.screenshot_artifact_id ? (
                    <button className="button secondary" disabled={actionBusy} onClick={() => void downloadScreenshot(action)} type="button">
                      Open evidence screenshot
                    </button>
                  ) : null}
                  {action.status === "pending" && action.takeover_handshake_status === "ready_to_open" ? (
                    <button className="button primary" disabled={actionBusy} onClick={() => void advance(action, "open")} type="button">
                      {busy === `${action.action_id}:open` ? "Recording…" : "Record local takeover handshake"}
                    </button>
                  ) : null}
                  {action.status === "pending" && action.continue_available && (
                    action.takeover_handshake_status === "opened" ||
                    action.takeover_handshake_status === "not_required"
                  ) ? (
                    <button className="button primary" disabled={actionBusy} onClick={() => void advance(action, "complete")} type="button">
                      {busy === `${action.action_id}:complete` ? "Verifying…" : "Confirm human action complete"}
                    </button>
                  ) : null}
                  {action.status === "pending" && action.cancel_available ? (
                    <button className="button secondary" disabled={actionBusy} onClick={() => void advance(action, "cancel")} type="button">
                      {busy === `${action.action_id}:cancel` ? "Cancelling…" : "Cancel and withdraw"}
                    </button>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
