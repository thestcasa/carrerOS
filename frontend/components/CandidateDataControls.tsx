"use client";

import { useEffect, useRef, useState } from "react";
import { clearActiveCandidate } from "@/lib/active-candidate";
import { api } from "@/lib/api";

function deletionKey(): string {
  return `candidate-delete-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`;
}

export function CandidateDataControls({
  candidateId,
}: {
  candidateId: string;
}) {
  return <CandidateDataControlState key={candidateId} candidateId={candidateId} />;
}

function CandidateDataControlState({ candidateId }: { candidateId: string }) {
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = useRef<{ candidateId: string; value: string } | null>(null);
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

  async function exportConfiguration() {
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

  async function deleteCandidate() {
    setBusy(true);
    setError(null);
    setMessage(null);
    if (key.current?.candidateId !== candidateId) {
      key.current = { candidateId, value: deletionKey() };
    }
    try {
      await api.deleteCandidate(candidateId, confirmation, key.current.value);
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
      <h2>Export and intentional deletion</h2>
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
        onClick={() => void exportConfiguration()}
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
