"use client";

import { useEffect, useRef, useState } from "react";
import { ErrorState, LoadingState } from "@/components/LoadingState";
import { CandidateDataControls } from "@/components/CandidateDataControls";
import { StatusPill } from "@/components/StatusPill";
import { api } from "@/lib/api";
import type { AtsPlatform, SettingsUpdate, SettingsView } from "@/lib/types";

function commandKey(prefix: string) {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`;
}

export function SettingsPageClient({ candidateId }: { candidateId: string }) {
  return <CandidateSettings key={candidateId} candidateId={candidateId} />;
}

function CandidateSettings({ candidateId }: { candidateId: string }) {
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [profileVersion, setProfileVersion] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [retentionDays, setRetentionDays] = useState(30);
  const mutationKeys = useRef(new Map<string, string>());

  function replayKey(operation: string, payload: object): string {
    const identity = `${candidateId}:${operation}:${JSON.stringify(payload)}`;
    const existing = mutationKeys.current.get(identity);
    if (existing) return existing;
    const created = commandKey(operation);
    mutationKeys.current.set(identity, created);
    return created;
  }

  useEffect(() => {
    let cancelled = false;
    api
      .settings(candidateId)
      .then((loaded) => {
        if (cancelled) return;
        setSettings(loaded);
        setRetentionDays(loaded.browser_session_retention_days);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Settings are unavailable.",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [candidateId]);
  useEffect(() => {
    let cancelled = false;
    api
      .candidate(candidateId)
      .then((candidate) => {
        if (!cancelled) setProfileVersion(candidate.profile_version);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(
            reason instanceof Error
              ? reason.message
              : "The current profile version is unavailable.",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [candidateId]);
  async function mode(automation_mode: SettingsView["automation_mode"]) {
    if (
      automation_mode === "autonomous" &&
      !globalThis.confirm(
        "Enable autonomous mode only after all displayed blockers are resolved?",
      )
    )
      return;
    setSaving(true);
    setError(null);
    const payload = { candidate_id: candidateId, automation_mode };
    const identity = `${candidateId}:settings-mode:${JSON.stringify(payload)}`;
    try {
      const updated = await api.updateSettings(
        payload,
        replayKey("settings-mode", payload),
      );
      mutationKeys.current.delete(identity);
      setSettings(updated);
      setRetentionDays(updated.browser_session_retention_days);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The backend denied this setting.",
      );
    } finally {
      setSaving(false);
    }
  }
  async function policy(update: Omit<SettingsUpdate, "candidate_id">) {
    setSaving(true);
    setError(null);
    const payload = { candidate_id: candidateId, ...update };
    const identity = `${candidateId}:settings-policy:${JSON.stringify(payload)}`;
    try {
      const updated = await api.updateSettings(
        payload,
        replayKey("settings-policy", payload),
      );
      mutationKeys.current.delete(identity);
      setSettings(updated);
      setRetentionDays(updated.browser_session_retention_days);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The backend denied this policy update.",
      );
    } finally {
      setSaving(false);
    }
  }
  function toggleAdapter(adapter: AtsPlatform) {
    if (!settings) return;
    const allowed_ats_adapters = settings.allowed_ats_adapters.includes(adapter)
      ? settings.allowed_ats_adapters.filter((item) => item !== adapter)
      : [...settings.allowed_ats_adapters, adapter];
    void policy({ allowed_ats_adapters });
  }
  async function stop() {
    if (!globalThis.confirm("Stop all new submissions immediately?")) return;
    setSaving(true);
    setError(null);
    const payload = { candidate_id: candidateId };
    const identity = `${candidateId}:emergency-stop:${JSON.stringify(payload)}`;
    try {
      const updated = await api.emergencyStop(
        candidateId,
        replayKey("emergency-stop", payload),
      );
      mutationKeys.current.delete(identity);
      setSettings(updated);
      setRetentionDays(updated.browser_session_retention_days);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The emergency stop could not be confirmed.",
      );
    } finally {
      setSaving(false);
    }
  }
  return (
    <div className="page-wrap">
      <header className="page-header">
        <div>
          <p className="eyebrow">Candidate automation policy</p>
          <h1>Settings</h1>
        </div>
        <p>
          Backend readiness is authoritative. The interface cannot enable
          autonomy while any blocker remains.
        </p>
      </header>
      {error ? <ErrorState message={error} /> : null}
      {!settings ? (
        <LoadingState label="Loading automation controls" />
      ) : (
        <div className="settings-grid">
          <section className="panel">
            <div className="panel-title">
              <div>
                <p className="eyebrow">Current mode</p>
                <h2>{settings.automation_mode.replaceAll("_", " ")}</h2>
              </div>
              <StatusPill
                status={settings.emergency_stopped ? "BLOCKED" : "READY"}
              />
            </div>
            <div className="mode-grid">
              {(
                [
                  "disabled",
                  "dry_run",
                  "approval_required",
                  "autonomous",
                ] as const
              ).map((item) => (
                <button
                  key={item}
                  className={`button ${settings.automation_mode === item ? "primary" : "secondary"}`}
                  disabled={
                    saving ||
                    (item === "autonomous" &&
                      settings.autonomy_blockers.length > 0)
                  }
                  onClick={() => void mode(item)}
                >
                  {item.replaceAll("_", " ")}
                </button>
              ))}
            </div>
            {settings.autonomy_blockers.length ? (
              <>
                <h3>Autonomy blockers</h3>
                <ul className="blocker-list">
                  {settings.autonomy_blockers.map((blocker) => (
                    <li key={blocker}>{blocker.replaceAll("_", " ")}</li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="form-message success">
                All autonomous-mode prerequisites are recorded.
              </p>
            )}
          </section>
          <section className="panel">
            <p className="eyebrow">Discovery policy</p>
            <h2>
              {settings.discovery_enabled
                ? "Scheduled discovery enabled"
                : "Scheduled discovery paused"}
            </h2>
            <label className="boolean-field">
              <input
                type="checkbox"
                checked={settings.discovery_enabled}
                disabled={saving}
                onChange={(event) =>
                  void policy({ discovery_enabled: event.target.checked })
                }
              />
              Enable read-only scheduled discovery
            </label>
            <h3>Allowed ATS adapters</h3>
            {(["greenhouse", "lever", "ashby"] as const).map((adapter) => (
              <label className="boolean-field" key={adapter}>
                <input
                  type="checkbox"
                  checked={settings.allowed_ats_adapters.includes(adapter)}
                  disabled={saving}
                  onChange={() => toggleAdapter(adapter)}
                />
                {adapter}
              </label>
            ))}
            <p>
              Manual fixture import remains available from the jobs page for
              development only.
            </p>
          </section>
          <section className="panel">
            <p className="eyebrow">Rate limits</p>
            <h2>Application boundaries</h2>
            <dl className="compact-metadata">
              <div>
                <dt>Daily</dt>
                <dd>{settings.maximum_applications_per_day}</dd>
              </div>
              <div>
                <dt>Weekly</dt>
                <dd>{settings.maximum_applications_per_week}</dd>
              </div>
              <div>
                <dt>Per company / 30 days</dt>
                <dd>{settings.maximum_applications_per_company_30_days}</dd>
              </div>
            </dl>
            <p>
              Tested ATS: {settings.tested_ats_adapters.join(", ") || "None"}
            </p>
            <div className="form-field">
              <span>Confirmed browser-session retention</span>
              <input
                aria-label="Confirmed browser-session retention"
                type="number"
                min={1}
                max={3650}
                value={retentionDays}
                disabled={saving}
                onChange={(event) =>
                  setRetentionDays(Number(event.target.value))
                }
              />
              <button
                className="button secondary"
                type="button"
                disabled={
                  saving ||
                  retentionDays < 1 ||
                  retentionDays > 3650 ||
                  retentionDays === settings.browser_session_retention_days
                }
                onClick={() =>
                  void policy({ browser_session_retention_days: retentionDays })
                }
              >
                Save retention
              </button>
              <small>
                Submitted archives remain indefinite until intentional candidate
                deletion.
              </small>
            </div>
          </section>
          <section className="panel emergency-panel">
            <p className="eyebrow">Immediate control</p>
            <h2>Emergency stop</h2>
            <p>
              Prevents all new submission authorizations while preserving
              in-progress state and audit history.
            </p>
            <button
              className="button danger"
              disabled={saving}
              onClick={() => void stop()}
            >
              Activate emergency stop
            </button>
          </section>
        </div>
      )}
      <CandidateDataControls
        candidateId={candidateId}
        profileVersion={profileVersion}
      />
    </div>
  );
}
