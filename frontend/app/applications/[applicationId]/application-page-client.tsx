"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ErrorState, LoadingState } from "@/components/LoadingState";
import { MaterialPreview } from "@/components/MaterialPreview";
import { StatusPill } from "@/components/StatusPill";
import { api } from "@/lib/api";
import type { ApplicationDetail, ArtifactView, MaterialRevisionInput } from "@/lib/types";

function metadataString(value: unknown): string | null {
  return typeof value === "string" || typeof value === "number" ? String(value) : null;
}

export function ApplicationPageClient({
  candidateId,
  applicationId,
}: {
  candidateId: string;
  applicationId: string;
}) {
  const [application, setApplication] = useState<ApplicationDetail | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactView[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const commandKeys = useRef(new Map<string, string>());
  function commandKey(operation: string): string {
    const identity = `${candidateId}:${applicationId}:${operation}`;
    const existing = commandKeys.current.get(identity);
    if (existing) return existing;
    const created = `${operation}-${globalThis.crypto.randomUUID()}`;
    commandKeys.current.set(identity, created);
    return created;
  }
  function clearCommand(operation: string) {
    commandKeys.current.delete(`${candidateId}:${applicationId}:${operation}`);
  }
  const load = useCallback(async () => {
    const [detail, stored] = await Promise.all([
      api.application(candidateId, applicationId),
      api.artifacts(candidateId, applicationId),
    ]);
    setApplication(detail);
    setArtifacts(stored);
  }, [candidateId, applicationId]);

  useEffect(() => {
    let active = true;
    void Promise.all([
      api.application(candidateId, applicationId),
      api.artifacts(candidateId, applicationId),
    ])
      .then(([detail, stored]) => {
        if (!active) return;
        setApplication(detail);
        setArtifacts(stored);
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(
            reason instanceof Error ? reason.message : "Application detail is unavailable.",
          );
        }
      });
    return () => {
      active = false;
    };
  }, [candidateId, applicationId]);

  const browserTaskPending =
    application?.state === "form_filling" &&
    (application.last_event === "BROWSER_DRY_RUN_QUEUED" ||
      application.last_event === "BROWSER_DRY_RUN_FAILED");

  useEffect(() => {
    if (!browserTaskPending) return;
    const timer = window.setInterval(() => {
      void load().catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "Browser task status is unavailable.");
      });
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [browserTaskPending, load]);

  async function action(
    kind: "approve-materials" | "start" | "dry-run" | "authorize-submit",
  ) {
    setBusy(true);
    setError(null);
    try {
      if (kind === "dry-run") {
        await api.dryRun(candidateId, applicationId, null, commandKey("dry-run"));
      } else if (kind === "authorize-submit") {
        const authorization = await api.authorize(
          candidateId,
          applicationId,
          commandKey("authorize"),
        );
        await api.submitSynthetic(
          candidateId,
          applicationId,
          authorization.authorization_id,
          commandKey("submit"),
        );
        clearCommand("authorize");
        clearCommand("submit");
      } else {
        await api.applicationCommand(
          candidateId,
          applicationId,
          kind,
          commandKey(kind),
        );
      }
      if (kind !== "authorize-submit") clearCommand(kind);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The operation failed safely.");
    } finally {
      setBusy(false);
    }
  }

  async function download(artifact: ArtifactView) {
    setError(null);
    try {
      const blob = await api.downloadArtifact(
        candidateId,
        applicationId,
        artifact.artifact_id,
      );
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${artifact.kind}-v${artifact.version}`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Artifact download failed safely.");
    }
  }

  async function prepareInterview() {
    setBusy(true);
    setError(null);
    try {
      await api.prepareInterview(
        candidateId,
        applicationId,
        commandKey("prepare-interview"),
      );
      clearCommand("prepare-interview");
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Interview preparation failed safely.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function reviseMaterial(revision: MaterialRevisionInput): Promise<ApplicationDetail> {
    const operation = `revise-material:${JSON.stringify(revision)}`;
    setBusy(true);
    setError(null);
    try {
      const updated = await api.reviseMaterial(
        candidateId,
        applicationId,
        revision,
        commandKey(operation),
      );
      clearCommand(operation);
      setApplication(updated);
      try {
        setArtifacts(await api.artifacts(candidateId, applicationId));
      } catch {
        setError("The revision was saved, but its downloadable artifacts could not be refreshed.");
      }
      return updated;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Material revision failed safely.");
      throw reason;
    } finally {
      setBusy(false);
    }
  }

  if (error && !application) {
    return (
      <div className="page-wrap">
        <ErrorState message={error} retry={() => void load()} />
      </div>
    );
  }
  if (!application) {
    return (
      <div className="page-wrap">
        <LoadingState label="Loading immutable application history" />
      </div>
    );
  }
  const nextAction =
    application.state === "review_pending"
      ? "approve-materials"
      : application.state === "application_started"
        ? "start"
        : application.state === "form_filling" && !browserTaskPending
          ? "dry-run"
          : application.state === "ready_to_submit"
            ? "authorize-submit"
            : null;

  return (
    <div className="page-wrap wide-page application-detail">
      <header className="page-header">
        <div>
          <p className="eyebrow">{application.company}</p>
          <h1>{application.role}</h1>
          <p>Candidate {candidateId} · score {application.score ?? "not available"}</p>
        </div>
        <div>
          <StatusPill status={application.state} />
          <br />
          <Link href={`/applications?candidate_id=${encodeURIComponent(candidateId)}`}>
            Back to pipeline
          </Link>
        </div>
      </header>
      {error ? <ErrorState message={error} /> : null}
      <section className="panel action-panel">
        <div>
          <p className="eyebrow">Authoritative backend state</p>
          <h2>{application.next_action}</h2>
          <p className="muted">
            {browserTaskPending
              ? "The isolated browser worker owns this attempt. This page refreshes from durable state; no submit control is available to the worker."
              : "The interface updates only from the persisted API response."}
          </p>
        </div>
        {nextAction ? (
          <button
            className="button primary"
            disabled={busy}
            onClick={() => void action(nextAction)}
          >
            {busy ? "Working…" : nextAction.replaceAll("-", " ")}
          </button>
        ) : null}
        {application.state === "interview" ? (
          <button
            className="button primary"
            disabled={busy}
            onClick={() => void prepareInterview()}
          >
            Prepare interview package
          </button>
        ) : null}
      </section>
      <MaterialPreview
        application={application}
        disabled={busy}
        onSaveRevision={reviseMaterial}
      />
      <section className="panel">
        <p className="eyebrow">Exact answers</p>
        <h2>Application questions</h2>
        {application.answers.map((answer) => (
          <div className="answer-row" key={answer.answer_id}>
            <strong>{answer.question}</strong>
            <p>{answer.answer}</p>
            <StatusPill status={answer.supported ? "READY" : "BLOCKED"} />
          </div>
        ))}
      </section>
      <section className="panel">
        <p className="eyebrow">Correspondence</p>
        <h2>Recruiting timeline</h2>
        {application.correspondence.length ? (
          <ol className="timeline">
            {application.correspondence.map((message) => (
              <li key={message.correspondence_id}>
                <span>{new Date(message.received_at).toLocaleString()}</span>
                <strong>{message.kind.replaceAll("_", " ")}</strong>
                <small>{message.subject}</small>
              </li>
            ))}
          </ol>
        ) : (
          <p className="muted">No associated recruiter correspondence.</p>
        )}
      </section>
      <section className="panel">
        <p className="eyebrow">Archive and receipt</p>
        <h2>{application.confirmation_reference ?? "No backend confirmation yet"}</h2>
        {artifacts.length ? (
          <ul className="artifact-list">
            {artifacts.map((artifact) => (
              <li key={artifact.artifact_id}>
                <span>{artifact.kind} v{artifact.version} · {artifact.immutable ? "immutable" : "draft"}</span>
                {artifact.kind.startsWith("rendered_") || artifact.kind.startsWith("render_report_") ? (
                  <small>
                    Template {metadataString(artifact.metadata.template_id) ?? "unknown"}@
                    {metadataString(artifact.metadata.template_version) ?? "unknown"} · snapshot {metadataString(artifact.metadata.candidate_snapshot_version) ?? "unknown"} · {metadataString(artifact.metadata.page_count) ?? "0"} page(s) · extraction {artifact.metadata.extraction_matches === true ? "matched" : "blocked"} · validation {artifact.metadata.valid === true ? "passed" : "blocked"}
                  </small>
                ) : null}
                <code>{artifact.sha256}</code>
                <button className="text-button" type="button" onClick={() => void download(artifact)}>
                  Download exact artifact
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">The pre-submit archive is created immediately before authorization.</p>
        )}
      </section>
      <section className="panel">
        <p className="eyebrow">Append-only audit</p>
        <h2>State timeline</h2>
        <ol className="timeline">
          {application.events.map((event) => (
            <li key={event.event_id}>
              <span>{new Date(event.occurred_at).toLocaleString()}</span>
              <strong>{event.event_type.replaceAll("_", " ")}</strong>
              <small>{event.from_state} → {event.to_state}</small>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
