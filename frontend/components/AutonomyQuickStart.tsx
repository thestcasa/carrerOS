"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { api } from "@/lib/api";
import type { SettingsView } from "@/lib/types";

function commandKey(prefix: string): string {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`;
}

export function AutonomyQuickStart({
  candidateId,
  settings,
  onChange,
}: {
  candidateId: string;
  settings: SettingsView;
  onChange: (settings: SettingsView) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const confirmKey = useRef<string | null>(null);
  const modeKey = useRef<string | null>(null);
  const blockers = settings.autonomy_prerequisites.filter(
    (item) => !item.passed && item.code !== "explicit_confirmation_missing",
  );
  const configurationBlockers = settings.autonomy_blockers.filter(
    (code) =>
      code !== "explicit_confirmation_missing" &&
      !settings.autonomy_prerequisites.some((item) => item.code === code),
  );
  const firstBlocker = blockers[0];
  const active =
    settings.automation_mode === "autonomous" &&
    !settings.emergency_stopped &&
    settings.autonomy_blockers.length === 0;
  const needsConfirmation = !settings.explicit_autonomy_confirmation;

  async function start() {
    setBusy(true);
    setMessage(null);
    try {
      let next = settings;
      if (needsConfirmation) {
        confirmKey.current ??= commandKey("confirm-autonomy");
        next = await api.confirmAutonomy(candidateId, confirmKey.current);
        confirmKey.current = null;
      }
      modeKey.current ??= commandKey("start-autonomy");
      next = await api.updateSettings(
        { candidate_id: candidateId, automation_mode: "autonomous", discovery_enabled: true },
        modeKey.current,
      );
      modeKey.current = null;
      onChange(next);
      setMessage("Autonomy started. Career OS will still run every safety check before any action.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Autonomy could not be started.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={active ? "autonomy-card active" : "autonomy-card"} aria-labelledby="autonomy-title">
      <div>
        <p className="eyebrow">Automatic job search</p>
        <h2 id="autonomy-title">{active ? "Autonomy is active" : "Let Career OS keep searching"}</h2>
        <p>
          {active
            ? "We are finding and preparing opportunities within your limits."
            : "Career OS finds jobs and prepares applications. CAPTCHA, sensitive questions, and unsafe submissions always require you."}
        </p>
      </div>
      {settings.emergency_stopped ? (
        <p className="form-message error">Emergency stop is active. No new application can start.</p>
      ) : firstBlocker || configurationBlockers.length ? (
        <Link
          className="button primary"
          href={firstBlocker?.action_href ?? `/candidates/${encodeURIComponent(candidateId)}/readiness`}
        >
          Complete setup
        </Link>
      ) : active ? (
        <Link className="button secondary" href={`/settings?candidate_id=${encodeURIComponent(candidateId)}`}>
          Manage autonomy
        </Link>
      ) : (
        <>
          {needsConfirmation ? (
            <label className="quick-confirmation">
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={(event) => setAcknowledged(event.target.checked)}
              />
              <span>
                I confirm these limits and understand that I can stop autonomy at any time.
              </span>
            </label>
          ) : null}
          <button
            className="button primary autonomy-start"
            type="button"
            disabled={busy || (needsConfirmation && !acknowledged)}
            onClick={() => void start()}
          >
            {busy ? "Starting..." : "Start autonomy"}
          </button>
        </>
      )}
      <div className="autonomy-limits" aria-label="Autonomy limits">
        <span>Max {settings.maximum_applications_per_day}/day</span>
        <span>Max {settings.maximum_applications_per_week}/week</span>
        <span>{settings.tested_ats_adapters.length} tested ATS</span>
      </div>
      {message ? <p className="form-message" role="status">{message}</p> : null}
      <details>
        <summary>How it works and which checks remain active</summary>
        <p>
          Readiness, legal status, duplicates, rate limits, the official source, and reviewed
          materials are checked again by the backend. This action never directly authorizes a submission.
        </p>
      </details>
    </section>
  );
}
