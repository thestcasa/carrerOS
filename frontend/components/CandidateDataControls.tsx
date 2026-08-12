"use client";

import { useEffect, useRef, useState } from "react";
import { clearActiveCandidate } from "@/lib/active-candidate";
import { api } from "@/lib/api";
import type { CandidateConfigurationFormat } from "@/lib/types";

const MAX_CONFIGURATION_FILE_SIZE = 1024 * 1024;

function deletionKey(): string {
  return `candidate-delete-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`;
}

function importKey(): string {
  return `candidate-configuration-import-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`;
}

function configurationFileFormat(
  filename: string,
): CandidateConfigurationFormat | null {
  const lower = filename.toLowerCase();
  if (lower.endsWith(".json")) return "json";
  if (lower.endsWith(".yaml") || lower.endsWith(".yml")) return "yaml";
  return null;
}

async function readUtf8(file: File): Promise<string> {
  const bytes = await new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error);
    reader.onload = () => {
      if (reader.result instanceof ArrayBuffer) resolve(reader.result);
      else reject(new Error("The selected file could not be read as bytes."));
    };
    reader.readAsArrayBuffer(file);
  });
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}

export function CandidateDataControls({
  candidateId,
  profileVersion,
}: {
  candidateId: string;
  profileVersion: string | null;
}) {
  return (
    <CandidateDataControlState
      key={`${candidateId}:${profileVersion ?? "unavailable"}`}
      candidateId={candidateId}
      profileVersion={profileVersion}
    />
  );
}

function CandidateDataControlState({
  candidateId,
  profileVersion,
}: {
  candidateId: string;
  profileVersion: string | null;
}) {
  const [confirmation, setConfirmation] = useState("");
  const [currentProfileVersion, setCurrentProfileVersion] =
    useState(profileVersion);
  const [configurationFile, setConfigurationFile] = useState<{
    name: string;
    format: CandidateConfigurationFormat;
    content: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const deletionIdempotencyKey = useRef<{
    candidateId: string;
    value: string;
  } | null>(null);
  const importIdempotencyKeys = useRef(new Map<string, string>());
  const fileInput = useRef<HTMLInputElement | null>(null);
  const mounted = useRef(true);
  const protectedTemplate = candidateId === "example_candidate";

  useEffect(() => {
    mounted.current = true;
    void api
      .deletionStatus(candidateId)
      .then((receipt) => {
        if (!mounted.current) return;
        if (receipt.status === "completed") {
          clearActiveCandidate(candidateId);
          window.history.replaceState({}, "", "/candidates");
          window.dispatchEvent(new PopStateEvent("popstate"));
          return;
        }
        setMessage(
          receipt.status === "deleting"
            ? "Deletion was interrupted after it was safely fenced. Confirm the candidate ID and retry to finish it."
            : "A previous deletion attempt failed safely. Confirm the candidate ID and retry to finish it.",
        );
      })
      .catch((reason: unknown) => {
        if (
          mounted.current &&
          (!reason ||
            typeof reason !== "object" ||
            !("code" in reason) ||
            reason.code !== "deletion_not_found")
        ) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Deletion recovery status is unavailable.",
          );
        }
      });
    return () => {
      mounted.current = false;
    };
  }, [candidateId]);

  async function exportCandidateData() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const data = await api.exportCandidate(candidateId);
      const blob = new Blob([`${JSON.stringify(data, null, 2)}\n`], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${candidateId}-portable-export.json`;
      link.click();
      globalThis.setTimeout(() => URL.revokeObjectURL(url), 0);
      if (mounted.current) {
        setMessage(
          "Portable export prepared with configuration, workflow records, and exact archives.",
        );
      }
    } catch (reason) {
      if (mounted.current) {
        setError(
          reason instanceof Error ? reason.message : "Candidate export failed.",
        );
      }
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  async function downloadConfiguration(format: CandidateConfigurationFormat) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const content = await api.exportCandidateConfiguration(
        candidateId,
        format,
      );
      const blob = new Blob([content], {
        type: format === "json" ? "application/json" : "application/yaml",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${candidateId}-configuration.${format}`;
      link.click();
      globalThis.setTimeout(() => URL.revokeObjectURL(url), 0);
      if (mounted.current) {
        setMessage(
          `${format.toUpperCase()} configuration bundle prepared. It contains source configuration only, without application workflow records or archive data.`,
        );
      }
    } catch (reason) {
      if (mounted.current) {
        setError(
          reason instanceof Error
            ? reason.message
            : "Configuration export failed.",
        );
      }
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  async function selectConfigurationFile(file: File | undefined) {
    setMessage(null);
    setError(null);
    setConfigurationFile(null);
    if (!file) return;
    const format = configurationFileFormat(file.name);
    if (!format) {
      setError("Choose a .json, .yaml, or .yml configuration bundle.");
      return;
    }
    if (file.size > MAX_CONFIGURATION_FILE_SIZE) {
      setError("Configuration bundles must be 1 MiB or smaller.");
      return;
    }
    try {
      const content = await readUtf8(file);
      if (mounted.current) {
        setConfigurationFile({ name: file.name, format, content });
      }
    } catch {
      if (mounted.current) {
        setError("The configuration bundle must be valid UTF-8 text.");
      }
    }
  }

  async function importConfiguration() {
    if (!configurationFile || !currentProfileVersion) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    const identity = `${currentProfileVersion}:${configurationFile.format}:${configurationFile.content}`;
    const idempotencyKey =
      importIdempotencyKeys.current.get(identity) ?? importKey();
    importIdempotencyKeys.current.set(identity, idempotencyKey);
    try {
      const result = await api.importCandidateConfiguration(
        candidateId,
        {
          format: configurationFile.format,
          content: configurationFile.content,
          expected_profile_version: currentProfileVersion,
        },
        idempotencyKey,
      );
      if (!mounted.current) return;
      importIdempotencyKeys.current.delete(identity);
      setCurrentProfileVersion(result.profile_version);
      setConfigurationFile(null);
      if (fileInput.current) fileInput.current.value = "";
      setMessage(
        result.changed
          ? `Configuration imported as profile version ${result.profile_version}. Workflow records and archives were not changed.`
          : "The imported configuration already matches this candidate. No new profile version was created.",
      );
    } catch (reason) {
      if (mounted.current) {
        setError(
          reason instanceof Error
            ? reason.message
            : "Configuration import failed safely.",
        );
      }
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  async function deleteCandidate() {
    setBusy(true);
    setError(null);
    setMessage(null);
    if (deletionIdempotencyKey.current?.candidateId !== candidateId) {
      deletionIdempotencyKey.current = {
        candidateId,
        value: deletionKey(),
      };
    }
    try {
      await api.deleteCandidate(
        candidateId,
        confirmation,
        deletionIdempotencyKey.current.value,
      );
      clearActiveCandidate(candidateId);
      if (!mounted.current) return;
      window.history.replaceState({}, "", "/candidates");
      window.dispatchEvent(new PopStateEvent("popstate"));
    } catch (reason) {
      if (mounted.current) {
        setError(
          reason instanceof Error
            ? reason.message
            : "Candidate deletion failed safely.",
        );
      }
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <section className="panel data-controls" aria-busy={busy}>
      <p className="eyebrow">Data management</p>
      <h2>Configuration portability</h2>
      <p>
        Configuration bundles contain only the candidate profile and policy
        sections. They do not restore workflow records, browser state, or
        archives. Import replaces all configuration sections together and
        creates one immutable profile version when data changes.
      </p>
      <div className="button-row">
        <button
          className="button secondary"
          type="button"
          disabled={busy}
          onClick={() => void downloadConfiguration("json")}
        >
          Download configuration JSON
        </button>
        <button
          className="button secondary"
          type="button"
          disabled={busy}
          onClick={() => void downloadConfiguration("yaml")}
        >
          Download configuration YAML
        </button>
      </div>
      <div className="deletion-confirmation">
        <label className="form-field">
          <span>Configuration bundle (.json, .yaml, or .yml; maximum 1 MiB)</span>
          <input
            ref={fileInput}
            type="file"
            accept=".json,.yaml,.yml,application/json,application/yaml,text/yaml"
            disabled={busy}
            onChange={(event) =>
              void selectConfigurationFile(event.target.files?.[0])
            }
          />
        </label>
        {configurationFile ? (
          <p className="form-message">Selected {configurationFile.name}</p>
        ) : null}
        <button
          className="button secondary"
          type="button"
          disabled={busy || !configurationFile || !currentProfileVersion}
          onClick={() => void importConfiguration()}
        >
          Import configuration
        </button>
        {!currentProfileVersion ? (
          <p className="form-message error">
            Import is unavailable until the current profile version is loaded.
          </p>
        ) : null}
      </div>
      <h2>Complete candidate export and intentional deletion</h2>
      <p>
        The portable JSON export includes configuration history, workflow
        records, shared-job evidence used by this candidate, and exact archive
        bytes. Browser credentials and secret tokens are excluded. Intentional
        deletion removes configuration, workflow rows, browser data, and
        immutable archives while retaining a minimal deletion receipt and
        administrative audit.
      </p>
      <p>Deletion is permanent and cannot be undone.</p>
      <button
        className="button secondary"
        type="button"
        disabled={busy}
        onClick={() => void exportCandidateData()}
      >
        Download candidate export
      </button>
      {protectedTemplate ? (
        <p className="form-message">
          The fictional onboarding template is protected from deletion.
        </p>
      ) : (
        <div className="deletion-confirmation">
          <label className="form-field">
            <span>
              Type <strong>{candidateId}</strong> to delete this candidate
            </span>
            <input
              value={confirmation}
              autoComplete="off"
              onChange={(event) => setConfirmation(event.target.value)}
            />
          </label>
          <button
            className="button danger"
            type="button"
            disabled={busy || confirmation !== candidateId}
            onClick={() => void deleteCandidate()}
          >
            Delete candidate and archives
          </button>
        </div>
      )}
      {message ? (
        <p className="form-message success" role="status">
          {message}
        </p>
      ) : null}
      {error ? (
        <p className="form-message error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}
