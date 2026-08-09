"use client";

import { useEffect, useRef, useState } from "react";
import { ErrorState, LoadingState } from "@/components/LoadingState";
import { CandidateDataControls } from "@/components/CandidateDataControls";
import { StatusPill } from "@/components/StatusPill";
import { api } from "@/lib/api";
import type { AtsPlatform, CandidateDetail, DiscoverySourceView, HumanActionView, JsonValue, SettingsUpdate, SettingsView } from "@/lib/types";

function commandKey(prefix: string) {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`;
}

const blockerLabels: Record<string, string> = {
  candidate_profile_not_approved: "Approve the candidate profile before enabling autonomy.",
  legal_status_not_approved: "Review and approve the legal and work-authorization answers.",
  automatic_answers_not_approved: "Approve the reusable application answers.",
  cv_templates_not_approved: "Approve the CV templates used for applications.",
  automatic_submission_disabled: "Enable automatic submission in the candidate workflow first.",
  no_allowed_ats_adapter: "Choose at least one ATS adapter that may be used.",
  no_tested_ats_adapter: "Run a passing safe adapter check for an allowed ATS.",
  dry_run_acceptance_not_passed: "Complete a passing candidate-scoped browser dry run.",
  explicit_confirmation_missing: "Read the consequences and record your own confirmation.",
  emergency_stop_active: "Review the emergency stop before enabling any automation.",
};

function blockerLabel(code: string): string {
  return blockerLabels[code] ?? "Resolve this backend readiness requirement before continuing.";
}

function stringList(value: JsonValue | undefined): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function configList(candidate: CandidateDetail | null, section: string, key: string): string[] {
  return stringList(candidate?.config[section]?.[key]);
}

export function SettingsPageClient({ candidateId }: { candidateId: string }) {
  return <CandidateSettings key={candidateId} candidateId={candidateId} />;
}

function CandidateSettings({ candidateId }: { candidateId: string }) {
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [profileVersion, setProfileVersion] = useState<string | null>(null);
  const [candidate, setCandidate] = useState<CandidateDetail | null>(null);
  const [sources, setSources] = useState<DiscoverySourceView[]>([]);
  const [humanActions, setHumanActions] = useState<HumanActionView[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [retentionDays, setRetentionDays] = useState(30);
  const [confirmationChecked, setConfirmationChecked] = useState(false);
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
    Promise.all([
      api.candidate(candidateId),
      api.discoverySources(candidateId),
      api.humanActions(candidateId),
    ])
      .then(([loadedCandidate, loadedSources, loadedActions]) => {
        if (!cancelled) {
          setCandidate(loadedCandidate);
          setProfileVersion(loadedCandidate.profile_version);
          setSources(loadedSources);
          setHumanActions(loadedActions);
        }
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
  async function confirmAutonomy() {
    if (!confirmationChecked) return;
    setSaving(true);
    setError(null);
    const payload = { candidate_id: candidateId, consequence_version: "autonomy-consequences-v1" };
    const identity = `${candidateId}:autonomy-confirmation:${JSON.stringify(payload)}`;
    try {
      const updated = await api.confirmAutonomy(
        candidateId,
        replayKey("autonomy-confirmation", payload),
      );
      mutationKeys.current.delete(identity);
      setSettings(updated);
      setConfirmationChecked(false);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The backend could not record this confirmation.",
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
            <p
              className={
                settings.controlled_submission_enabled
                  ? "form-message warning"
                  : "form-message"
              }
            >
              {settings.controlled_submission_enabled
                ? "Live controlled submission is available only to the isolated submission worker and remains gate-authorized."
                : "Live controlled submission is disabled at the process boundary."}
            </p>
            {settings.autonomy_prerequisites.length ? (
              <>
                <h3>Safe autonomy checklist</h3>
                <div className="autonomy-checklist">
                  {settings.autonomy_prerequisites.map((prerequisite) => (
                    <article className="autonomy-prerequisite" key={prerequisite.code}>
                      <StatusPill status={prerequisite.passed ? "READY" : "BLOCKED"} />
                      <h4>{prerequisite.title}</h4>
                      <p>{prerequisite.explanation}</p>
                      {prerequisite.evidence_summary ? (
                        <p className="form-message success">Evidence: {prerequisite.evidence_summary}</p>
                      ) : (
                        <p className="muted">Next: {prerequisite.resolution}</p>
                      )}
                      {!prerequisite.passed && prerequisite.code !== "explicit_confirmation_missing" ? (
                        <a href={prerequisite.action_href}>Open the safe next step →</a>
                      ) : null}
                    </article>
                  ))}
                </div>
              </>
            ) : (
              <p className="form-message success">
                All autonomous-mode prerequisites are recorded.
              </p>
            )}
            {settings.autonomy_blockers.filter((blocker) =>
              !settings.autonomy_prerequisites.some((item) => item.code === blocker),
            ).length ? (
              <div className="form-message warning">
                <strong>Candidate configuration still needs attention.</strong>
                <ul className="blocker-list">
                  {settings.autonomy_blockers
                    .filter((blocker) =>
                      !settings.autonomy_prerequisites.some((item) => item.code === blocker),
                    )
                    .map((blocker) => (
                      <li key={blocker}>{blockerLabel(blocker)}</li>
                    ))}
                </ul>
              </div>
            ) : null}
            <div id="autonomy-confirmation" className="confirmation-panel">
              <h3>Explicit autonomy confirmation</h3>
              <p>
                Autonomous mode may queue controlled submissions only for the tested adapter
                pattern, within the displayed daily, weekly, and company limits. The emergency
                stop prevents new authorizations, but it cannot undo an already armed final click.
              </p>
              <label className="boolean-field">
                <input
                  type="checkbox"
                  checked={confirmationChecked}
                  disabled={
                    saving ||
                    !settings.tested_ats_adapters.length ||
                    !settings.dry_run_acceptance_passed ||
                    settings.explicit_autonomy_confirmation
                  }
                  onChange={(event) => setConfirmationChecked(event.target.checked)}
                />
                I understand these consequences and confirm this exact scope.
              </label>
              <button
                className="button primary"
                type="button"
                disabled={
                  saving ||
                  !confirmationChecked ||
                  settings.explicit_autonomy_confirmation
                }
                onClick={() => void confirmAutonomy()}
              >
                Record my confirmation
              </button>
              {settings.explicit_autonomy_confirmation ? (
                <p className="form-message success">Your current scoped confirmation is audited.</p>
              ) : null}
            </div>
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
            <p className="eyebrow">Operational configuration</p>
            <h2>Sources, targeting, and integrations</h2>
            <dl className="compact-metadata">
              <div><dt>Discovery cadence</dt><dd>{sources.length ? sources.map((source) => `${source.company}: ${source.cadence_minutes} min${source.enabled ? "" : " (paused)"}`).join(" · ") : "No scheduled sources"}</dd></div>
              <div><dt>Target companies</dt><dd>{configList(candidate, "companies", "target").join(", ") || "Not configured"}</dd></div>
              <div><dt>Target roles</dt><dd>{configList(candidate, "roles", "target").join(", ") || configList(candidate, "career_strategy", "target_roles").join(", ") || "Not configured"}</dd></div>
              <div><dt>Salary policy</dt><dd>{candidate?.config.preferences?.salary && typeof candidate.config.preferences.salary === "object" && !Array.isArray(candidate.config.preferences.salary) ? `${candidate.config.preferences.salary.currency ?? "Currency unset"} ${candidate.config.preferences.salary.minimum ?? "minimum unset"}–${candidate.config.preferences.salary.maximum ?? "maximum unset"}` : "Not configured"}</dd></div>
              <div><dt>Role threshold</dt><dd>{String(candidate?.config.scoring_rules?.application_threshold ?? "Not configured")}</dd></div>
              <div><dt>Browser profiles</dt><dd>{humanActions.some((action) => action.browser_session_health !== "unavailable") ? humanActions.map((action) => action.browser_session_health.replaceAll("_", " ")).join(", ") : "No active browser session"}</dd></div>
              <div><dt>Analysis model</dt><dd>Local deterministic scoring v1; provider credentials are never exposed to the browser.</dd></div>
              <div><dt>Notification channels</dt><dd>{configList(candidate, "notification_rules", "channels").join(", ") || "Dashboard only"}</dd></div>
              <div><dt>ATS integration</dt><dd>{settings.tested_ats_adapters.length ? `${settings.tested_ats_adapters.join(", ")} synthetic acceptance passed` : "No durable adapter acceptance yet"}</dd></div>
            </dl>
            <div className="inline-actions">
              <a className="button secondary" href={`/jobs?candidate_id=${encodeURIComponent(candidateId)}`}>Manage sources</a>
              <a className="button secondary" href={`/candidates/${encodeURIComponent(candidateId)}/profile?section=career_strategy`}>Edit targeting</a>
              <a className="button secondary" href={`/candidates/${encodeURIComponent(candidateId)}/profile?section=notification_rules`}>Edit notifications</a>
            </div>
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
