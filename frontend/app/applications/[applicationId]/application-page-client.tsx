"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ErrorState, LoadingState } from "@/components/LoadingState";
import { StatusPill } from "@/components/StatusPill";
import { api } from "@/lib/api";
import type { ApplicationDetail, ArtifactView } from "@/lib/types";

function key(prefix: string) {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`;
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

  async function action(
    kind: "approve-materials" | "start" | "dry-run" | "authorize-submit",
  ) {
    setBusy(true);
    setError(null);
    try {
      if (kind === "dry-run") {
        await api.dryRun(candidateId, applicationId, null, key("dry-run"));
      } else if (kind === "authorize-submit") {
        const authorization = await api.authorize(
          candidateId,
          applicationId,
          key("authorize"),
        );
        await api.submitSynthetic(
          candidateId,
          applicationId,
          authorization.authorization_id,
          true,
          `synthetic-${Date.now()}`,
          key("submit"),
        );
      } else {
        await api.applicationCommand(candidateId, applicationId, kind, key(kind));
      }
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
        : application.state === "form_filling"
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
          <p className="muted">The interface updates only from the persisted API response.</p>
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
      </section>
      <section className="detail-columns">
        <article className="panel">
          <p className="eyebrow">Exact documents</p>
          <h2>{application.archive_available ? "Immutable submitted set" : "Versioned drafts"}</h2>
          {application.documents.map((document) => (
            <details key={document.document_id} open>
              <summary>{document.kind.replaceAll("_", " ")} v{document.version} · {document.immutable ? "immutable" : "draft"}</summary>
              <pre>{document.content}</pre>
              <p className="artifact-hash">SHA-256 {document.sha256}</p>
              <div>{document.evidence_ids.map((id) => <code key={id}>{id}</code>)}</div>
            </details>
          ))}
        </article>
        <article className="panel">
          <p className="eyebrow">Exact answers</p>
          <h2>Application questions</h2>
          {application.answers.map((answer) => (
            <div className="answer-row" key={answer.answer_id}>
              <strong>{answer.question}</strong>
              <p>{answer.answer}</p>
              <StatusPill status={answer.supported ? "READY" : "BLOCKED"} />
            </div>
          ))}
        </article>
      </section>
      <section className="panel">
        <p className="eyebrow">Archive and receipt</p>
        <h2>{application.confirmation_reference ?? "No backend confirmation yet"}</h2>
        {artifacts.length ? (
          <ul className="artifact-list">
            {artifacts.map((artifact) => (
              <li key={artifact.artifact_id}>
                <span>{artifact.kind} v{artifact.version} · {artifact.immutable ? "immutable" : "draft"}</span>
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
