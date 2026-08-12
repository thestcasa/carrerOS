"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ErrorState, LoadingState } from "@/components/LoadingState";
import { ApplicationTimeline } from "@/components/ApplicationTimeline";
import { MaterialPreview } from "@/components/MaterialPreview";
import { StatusPill } from "@/components/StatusPill";
import { SubmittedPackageViewer } from "@/components/SubmittedPackageViewer";
import { api } from "@/lib/api";
import type {
  AnswerRevisionInput,
  ApplicationAnswerView,
  ApplicationDetail,
  ArtifactView,
  MaterialPolicy,
  MaterialRevisionInput,
  SettingsView,
} from "@/lib/types";

function groupedAnswers(answers: ApplicationAnswerView[]): ApplicationAnswerView[][] {
  const groups = new Map<string, ApplicationAnswerView[]>();
  for (const answer of answers) {
    const group = groups.get(answer.question_key) ?? [];
    group.push(answer);
    groups.set(answer.question_key, group);
  }
  return [...groups.values()]
    .map((group) => group.sort((left, right) => right.version - left.version))
    .sort((left, right) => left[0].question.localeCompare(right[0].question));
}

function AnswerHistory({
  answers,
  disabled,
  onSaveRevision,
}: {
  answers: ApplicationAnswerView[];
  disabled: boolean;
  onSaveRevision: (revision: AnswerRevisionInput) => Promise<ApplicationDetail>;
}) {
  const latest = answers[0];
  const [selectedId, setSelectedId] = useState(latest.answer_id);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(latest.answer);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const selected = answers.find((answer) => answer.answer_id === selectedId) ?? latest;

  function select(answer: ApplicationAnswerView) {
    setSelectedId(answer.answer_id);
    setDraft(answer.answer);
    setReason("");
    setEditing(false);
  }

  async function save() {
    const revision: AnswerRevisionInput = {
      answer_id: selected.answer_id,
      base_version: selected.version,
      answer: draft,
      ...(reason.trim() ? { reason: reason.trim() } : {}),
    };
    setSaving(true);
    try {
      const updated = await onSaveRevision(revision);
      const updatedAnswers = updated.answers
        .filter((answer) => answer.question_key === selected.question_key)
        .sort((left, right) => right.version - left.version);
      const updatedLatest = updatedAnswers[0];
      if (updatedLatest) {
        setSelectedId(updatedLatest.answer_id);
        setDraft(updatedLatest.answer);
      }
      setReason("");
      setEditing(false);
    } catch {
      // The parent renders the API error; retain the exact draft for an idempotent retry.
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="answer-row" aria-label={latest.question}>
      <h3>{latest.question}</h3>
      <div aria-label={`Version history for ${latest.question}`}>
        {answers.map((answer) => (
          <button
            className="text-button"
            type="button"
            key={answer.answer_id}
            aria-current={answer.answer_id === selected.answer_id ? "true" : undefined}
            onClick={() => select(answer)}
          >
            Version {answer.version}{answer.answer_id === latest.answer_id ? " (latest)" : ""}
          </button>
        ))}
      </div>
      {editing ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <label htmlFor={`answer-content-${selected.answer_id}`}>Answer content</label>
          <textarea
            id={`answer-content-${selected.answer_id}`}
            maxLength={10_000}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <label htmlFor={`answer-reason-${selected.answer_id}`}>
            Revision reason (optional)
          </label>
          <input
            id={`answer-reason-${selected.answer_id}`}
            maxLength={500}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
          <p className="muted">
            Saving appends a version. The backend revalidates the answer and derives its
            evidence and candidate-snapshot provenance.
          </p>
          <div aria-live="polite">{saving ? "Saving answer revision…" : null}</div>
          <button
            className="button primary"
            type="submit"
            disabled={disabled || saving || !draft.trim() || draft === selected.answer}
          >
            Save as new answer version
          </button>
          <button
            className="text-button"
            type="button"
            disabled={saving}
            onClick={() => {
              setDraft(selected.answer);
              setReason("");
              setEditing(false);
            }}
          >
            Cancel answer edit
          </button>
        </form>
      ) : (
        <>
          <p>{selected.answer}</p>
          <StatusPill status={selected.supported ? "READY" : "BLOCKED"} />
          {!selected.immutable ? (
            <button
              className="text-button"
              type="button"
              disabled={disabled}
              onClick={() => {
                setDraft(selected.answer);
                setReason("");
                setEditing(true);
              }}
            >
              Edit latest answer
            </button>
          ) : (
            <p className="muted">Immutable answer history</p>
          )}
        </>
      )}
      <p className="eyebrow">Backend-derived provenance</p>
      <dl className="metadata-list">
        <div>
          <dt>Revision</dt>
          <dd>{selected.revision_kind.replaceAll("_", " ")} by {selected.revision_actor}</dd>
        </div>
        <div>
          <dt>Version state</dt>
          <dd>{selected.immutable ? "Immutable history" : "Latest editable answer"}</dd>
        </div>
        <div>
          <dt>Base answer</dt>
          <dd>{selected.base_answer_id ?? "Initial version"}</dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd>{new Date(selected.created_at).toLocaleString()}</dd>
        </div>
        <div>
          <dt>Reason</dt>
          <dd>{selected.reason ?? "No reason recorded"}</dd>
        </div>
        <div>
          <dt>Approved source</dt>
          <dd>{selected.approved_source_key ?? "Not recorded"}</dd>
        </div>
        <div>
          <dt>Evidence IDs</dt>
          <dd>{selectedIds(selected.evidence_ids)}</dd>
        </div>
        <div>
          <dt>Candidate snapshot</dt>
          <dd>
            {selected.candidate_snapshot_version ?? "Not recorded"}
            {selected.candidate_snapshot_id ? ` · ${selected.candidate_snapshot_id}` : ""}
          </dd>
        </div>
        <div>
          <dt>Candidate snapshot SHA-256</dt>
          <dd><code>{selected.candidate_snapshot_sha256 ?? "Not recorded"}</code></dd>
        </div>
        <div>
          <dt>Answer SHA-256</dt>
          <dd><code>{selected.sha256}</code></dd>
        </div>
      </dl>
    </section>
  );
}

function metadataString(value: unknown): string | null {
  return typeof value === "string" || typeof value === "number" ? String(value) : null;
}

function selectedIds(values: string[]): string {
  return values.length ? values.join(", ") : "None selected";
}

function MaterialPolicyPanel({ policy }: { policy: MaterialPolicy | null }) {
  return (
    <section className="panel" aria-labelledby="material-policy-heading">
      <p className="eyebrow">Persisted generation decision</p>
      <h2 id="material-policy-heading">Role-aware material policy</h2>
      {policy ? (
        <dl className="metadata-list">
          <div>
            <dt>Policy schema</dt>
            <dd>{policy.schema_version}</dd>
          </div>
          <div>
            <dt>Generator</dt>
            <dd>{policy.generator_version}</dd>
          </div>
          <div>
            <dt>Bound job version</dt>
            <dd>v{policy.job_version} · {policy.job_payload_sha256}</dd>
          </div>
          <div>
            <dt>CV template</dt>
            <dd>{policy.cv_template_id}@{policy.cv_template_version}</dd>
          </div>
          <div>
            <dt>Selected experience IDs</dt>
            <dd>{selectedIds(policy.selected_experience_ids)}</dd>
          </div>
          <div>
            <dt>Selected project IDs</dt>
            <dd>{selectedIds(policy.selected_project_ids)}</dd>
          </div>
          <div>
            <dt>Cover letter</dt>
            <dd>{policy.cover_letter.included ? "Included" : "Omitted"}</dd>
          </div>
          <div>
            <dt>Cover-letter reason</dt>
            <dd>{policy.cover_letter.reason ?? "No reason recorded"}</dd>
          </div>
          <div>
            <dt>Cover-letter experience IDs</dt>
            <dd>{selectedIds(policy.cover_letter.selected_experience_ids)}</dd>
          </div>
          <div>
            <dt>Cover-letter project IDs</dt>
            <dd>{selectedIds(policy.cover_letter.selected_project_ids)}</dd>
          </div>
          <div>
            <dt>Cover-letter word bounds</dt>
            <dd>{policy.cover_letter.minimum_words}–{policy.cover_letter.maximum_words} words</dd>
          </div>
        </dl>
      ) : (
        <p className="muted">No material policy has been persisted for this application.</p>
      )}
    </section>
  );
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
  const [controlledSubmissionEnabled, setControlledSubmissionEnabled] = useState(false);
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [approvalAcknowledged, setApprovalAcknowledged] = useState(false);
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
    const [detail, stored, settings] = await Promise.all([
      api.application(candidateId, applicationId),
      api.artifacts(candidateId, applicationId),
      api.settings(candidateId),
    ]);
    setApplication(detail);
    setArtifacts(stored);
    setSettings(settings);
    setControlledSubmissionEnabled(settings.controlled_submission_enabled === true);
  }, [candidateId, applicationId]);

  useEffect(() => {
    let active = true;
    void Promise.all([
      api.application(candidateId, applicationId),
      api.artifacts(candidateId, applicationId),
      api.settings(candidateId),
    ])
      .then(([detail, stored, settings]) => {
        if (!active) return;
        setApplication(detail);
        setArtifacts(stored);
        setSettings(settings);
        setControlledSubmissionEnabled(settings.controlled_submission_enabled === true);
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
  const controlledTaskPending =
    application?.state === "ready_to_submit" &&
    application.last_event === "CONTROLLED_SUBMISSION_QUEUED";

  useEffect(() => {
    if (!browserTaskPending && !controlledTaskPending) return;
    const timer = window.setInterval(() => {
      void load().catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "Browser task status is unavailable.");
      });
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [browserTaskPending, controlledTaskPending, load]);

  async function action(
    kind: "approve-materials" | "start" | "dry-run" | "authorize-submit",
  ) {
    setBusy(true);
    setError(null);
    try {
      if (kind === "dry-run") {
        await api.dryRun(candidateId, applicationId, null, commandKey("dry-run"));
      } else if (kind === "authorize-submit") {
        if (controlledSubmissionEnabled) {
          const authorization = await api.authorizeControlled(
            candidateId,
            applicationId,
            commandKey("controlled-authorize"),
          );
          await api.queueControlledSubmission(
            candidateId,
            applicationId,
            authorization.authorization_id,
            commandKey("controlled-submit"),
          );
          clearCommand("controlled-authorize");
          clearCommand("controlled-submit");
        } else {
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
        }
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
      if (kind === "authorize-submit") setApprovalAcknowledged(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The operation failed safely.");
    } finally {
      setBusy(false);
    }
  }

  async function acceptAdapter() {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.runAdapterAcceptance(
        candidateId,
        applicationId,
        commandKey("adapter-acceptance"),
      );
      clearCommand("adapter-acceptance");
      setSettings(updated);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The synthetic adapter check failed safely.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function download(artifact: ArtifactView) {
    setError(null);
    try {
      const extension = artifact.content_type === "application/pdf" ? ".pdf"
        : artifact.content_type === "application/x-tex" ? ".tex"
          : artifact.content_type === "application/json" ? ".json" : "";
      const blob = await api.downloadArtifact(
        candidateId,
        applicationId,
        artifact.artifact_id,
      );
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${artifact.kind}-v${artifact.version}${extension}`;
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

  async function reviseAnswer(revision: AnswerRevisionInput): Promise<ApplicationDetail> {
    const operation = `revise-answer:${JSON.stringify(revision)}`;
    setBusy(true);
    setError(null);
    try {
      const updated = await api.reviseAnswer(
        candidateId,
        applicationId,
        revision,
        commandKey(operation),
      );
      clearCommand(operation);
      setApplication(updated);
      return updated;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Answer revision failed safely.");
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
            ? controlledTaskPending
              ? null
              : "authorize-submit"
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
      {application.state === "unknown_after_click" ? (
        <section className="panel" role="alert">
          <p className="eyebrow">Manual investigation required</p>
          <h2>Submission outcome is unknown</h2>
          <p>
            Do not retry this application. Career OS has stopped automation and recorded the
            ambiguous click outcome for review.
          </p>
        </section>
      ) : null}
      {application.state === "human_action_required" ? (
        <section className="panel action-panel">
          <div>
            <p className="eyebrow">Human-only step</p>
            <h2>Review the evidence and resolve the pending action</h2>
            <p>Career OS has paused this application. It will not bypass verification.</p>
          </div>
          <Link
            className="button primary"
            href={`/actions?candidate_id=${encodeURIComponent(candidateId)}`}
          >
            Open human actions
          </Link>
        </section>
      ) : null}
      <section className="panel action-panel">
        <div>
          <p className="eyebrow">Authoritative backend state</p>
          <h2>{application.next_action}</h2>
          <p className="muted">
            {browserTaskPending
              ? "The isolated browser worker owns this attempt. This page refreshes from durable state; no submit control is available to the worker."
              : controlledTaskPending
                ? "The isolated controlled-submission worker owns this one-attempt task. The interface cannot issue another click."
              : "The interface updates only from the persisted API response."}
          </p>
        </div>
        {nextAction === "authorize-submit" ? (
          <div className="approval-confirmation">
            <p>
              {controlledSubmissionEnabled
                ? "This can arm one irreversible controlled final click after every backend check passes."
                : "This runs the fictional backend-confirmed submission only. Live controlled submission is disabled."}
            </p>
            <label className="boolean-field">
              <input
                type="checkbox"
                checked={approvalAcknowledged}
                disabled={busy}
                onChange={(event) => setApprovalAcknowledged(event.target.checked)}
              />
              I reviewed the materials and understand the consequence of continuing.
            </label>
          </div>
        ) : null}
        {application.state === "ready_to_submit" &&
        settings &&
        !settings.tested_ats_adapters.includes("greenhouse") ? (
          settings.allowed_ats_adapters.includes("greenhouse") ? (
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => void acceptAdapter()}
            >
              Run safe Greenhouse adapter check
            </button>
          ) : (
            <Link
              className="button secondary"
              href={`/settings?candidate_id=${encodeURIComponent(candidateId)}#allowed-ats-adapters`}
            >
              Allow Greenhouse before testing it
            </Link>
          )
        ) : null}
        {nextAction ? (
          <button
            className="button primary"
            disabled={busy || (nextAction === "authorize-submit" && !approvalAcknowledged)}
            onClick={() => void action(nextAction)}
          >
            {busy
              ? "Working…"
              : nextAction === "authorize-submit" && controlledSubmissionEnabled
                ? "Approve one controlled submission"
                : nextAction === "authorize-submit"
                  ? "Run fictional submission demo"
                : nextAction.replaceAll("-", " ")}
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
      <section className="panel application-progress-panel">
        <p className="eyebrow">Application progress</p>
        <h2>What is happening</h2>
        <ApplicationTimeline events={application.events} currentState={application.state} />
      </section>

      <MaterialPolicyPanel policy={application.material_policy} />
      <MaterialPreview
        application={application}
        disabled={busy}
        onSaveRevision={reviseMaterial}
      />
      <section className="panel">
        <p className="eyebrow">Exact answers</p>
        <h2>Application questions</h2>
        {application.answers.length ? (
          groupedAnswers(application.answers).map((answers) => (
            <AnswerHistory
              answers={answers}
              disabled={busy}
              key={answers[0].question_key}
              onSaveRevision={reviseAnswer}
            />
          ))
        ) : (
          <p className="muted">No application questions have been generated.</p>
        )}
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
      <SubmittedPackageViewer
        applicationId={applicationId}
        artifacts={artifacts}
        candidateId={candidateId}
        confirmationReference={application.confirmation_reference}
      />
      <section className="panel">
        <p className="eyebrow">Your files</p>
        <h2>{application.confirmation_reference ? "Submitted package and receipt" : "Application materials"}</h2>
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
                  {artifact.content_type === "application/pdf" ? "Download PDF" : artifact.content_type === "application/x-tex" ? "Download LaTeX source" : "Download file"}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">The pre-submit archive is created immediately before authorization.</p>
        )}
      </section>
      <details className="panel technical-details">
        <summary>Technical details and audit trail</summary>
        <h2>Raw state events</h2>
        <ol className="timeline">
          {application.events.map((event) => (
            <li key={event.event_id}>
              <span>{new Date(event.occurred_at).toLocaleString()}</span>
              <strong>{event.event_type.replaceAll("_", " ")}</strong>
              <small>{event.from_state} → {event.to_state}</small>
            </li>
          ))}
        </ol>
      </details>
    </div>
  );
}
