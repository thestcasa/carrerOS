"use client";

import { useMemo, useState } from "react";
import type {
  ApplicationDetail,
  ApplicationDocumentView,
  JsonObject,
  JsonValue,
  MaterialRevisionInput,
} from "@/lib/types";

function displayValue(value: JsonValue | undefined): string {
  if (typeof value === "boolean") return value ? "passed" : "blocked";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return "not recorded";
}

function stringList(value: JsonValue | undefined): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function provenanceText(entry: JsonObject): string {
  return typeof entry.text === "string" ? entry.text : "Recorded claim";
}

function MaterialReview({ application, document }: { application: ApplicationDetail; document: ApplicationDocumentView }) {
  const metadata = document.render_metadata;
  return (
    <section className="panel material-review" aria-labelledby="material-review-heading">
      <p className="eyebrow">Deterministic checks</p>
      <h2 id="material-review-heading">Render and independent review</h2>
      <dl className="metadata-list">
        <div><dt>Source validation</dt><dd>{document.validated ? "passed" : "blocked"}</dd></div>
        <div><dt>Review decision</dt><dd>{application.review?.decision.replaceAll("_", " ") ?? "not recorded"}</dd></div>
        <div><dt>Semantic review</dt><dd>{application.review?.semantic_passed ? "passed" : "blocked"}</dd></div>
        <div><dt>Template</dt><dd>{displayValue(metadata.template_id)}@{displayValue(metadata.template_version)}</dd></div>
        <div><dt>Pages</dt><dd>{displayValue(metadata.page_count)}</dd></div>
        <div><dt>Text extraction</dt><dd>{displayValue(metadata.extraction_matches)}</dd></div>
      </dl>
      {document.revision_actor ? (
        <p className="muted">
          Revised by {document.revision_actor}
          {document.base_document_id ? ` from ${document.base_document_id}` : ""}.
        </p>
      ) : null}
    </section>
  );
}

export function MaterialPreview({
  application,
  onSaveRevision,
  disabled = false,
}: {
  application: ApplicationDetail;
  onSaveRevision: (revision: MaterialRevisionInput) => Promise<ApplicationDetail>;
  disabled?: boolean;
}) {
  const ordered = useMemo(
    () =>
      [...application.documents].sort(
        (left, right) =>
          right.version - left.version ||
          left.kind.localeCompare(right.kind) ||
          left.document_id.localeCompare(right.document_id),
      ),
    [application.documents],
  );
  const [selectedId, setSelectedId] = useState(ordered[0]?.document_id ?? "");
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const document = ordered.find((item) => item.document_id === selectedId) ?? ordered[0];

  if (!document) {
    return <section className="empty-state"><h2>No material drafts</h2><p>Generate materials before starting review.</p></section>;
  }

  function select(next: ApplicationDocumentView) {
    setSelectedId(next.document_id);
    setEditing(false);
    setContent("");
    setReason("");
  }

  function startEditing() {
    setContent(document.content);
    setReason("");
    setEditing(true);
  }

  function cancelEditing() {
    setContent(document.content);
    setReason("");
    setEditing(false);
  }

  async function save() {
    setSaving(true);
    try {
      const updated = await onSaveRevision({
        document_id: document.document_id,
        base_version: document.version,
        content,
        ...(reason.trim() ? { reason: reason.trim() } : {}),
      });
      const latest = [...updated.documents]
        .filter((item) => item.kind === document.kind)
        .sort((left, right) => right.version - left.version)[0];
      if (latest) setSelectedId(latest.document_id);
      setEditing(false);
      setContent("");
      setReason("");
    } catch {
      // The parent renders the API error; keep this exact draft open for a safe retry.
    } finally {
      setSaving(false);
    }
  }

  const provenance: JsonObject[] = document.provenance;

  return (
    <div className="material-layout">
      <section className="panel action-panel" aria-labelledby="material-actions-heading">
        <div>
          <p className="eyebrow">Versioned application materials</p>
          <h2 id="material-actions-heading">Draft editor</h2>
          <p className="muted">A save appends a reviewed revision. Existing versions are never overwritten.</p>
        </div>
        {!editing ? (
          <button
            className="button secondary"
            disabled={disabled || document.immutable}
            onClick={startEditing}
            type="button"
          >
            Edit selected draft
          </button>
        ) : null}
      </section>

      <div className="material-grid">
        <aside className="panel version-panel" aria-labelledby="version-history-heading">
          <p className="eyebrow">Append-only history</p>
          <h2 id="version-history-heading">Document versions</h2>
          <ol className="version-list">
            {ordered.map((item) => (
              <li key={item.document_id}>
                <button
                  className={item.document_id === document.document_id ? "active" : ""}
                  aria-current={item.document_id === document.document_id ? "true" : undefined}
                  disabled={saving}
                  onClick={() => select(item)}
                  type="button"
                >
                  <strong>{item.kind.replaceAll("_", " ")} · version {item.version}</strong>
                  <span>{item.immutable ? "Immutable history" : "Latest editable draft"}</span>
                </button>
              </li>
            ))}
          </ol>
        </aside>

        <article className="panel document-preview" aria-labelledby="document-preview-heading">
          <div className="panel-title">
            <div>
              <p className="eyebrow">{document.kind.replaceAll("_", " ")} · version {document.version}</p>
              <h2 id="document-preview-heading">{application.role} · {application.company}</h2>
            </div>
            <span className={`material-state ${document.immutable ? "immutable" : "draft"}`}>
              {document.immutable ? "Immutable history" : "Editable draft"}
            </span>
          </div>
          {editing ? (
            <div className="material-editor">
              <label className="form-field" htmlFor="material-content">
                Material content
                <textarea
                  aria-label="Material content"
                  aria-describedby="material-edit-policy"
                  disabled={saving}
                  id="material-content"
                  onChange={(event) => setContent(event.target.value)}
                  rows={18}
                  value={content}
                />
              </label>
              <p className="muted" id="material-edit-policy">
                Keep the canonical heading and exact approved-fact bullet wording; bullets may be
                reordered or removed. Saving reruns validation and review.
              </p>
              <label className="form-field" htmlFor="material-revision-reason">
                Revision reason (optional)
                <input
                  aria-label="Revision reason (optional)"
                  disabled={saving}
                  id="material-revision-reason"
                  maxLength={500}
                  onChange={(event) => setReason(event.target.value)}
                  value={reason}
                />
              </label>
              <div className="editor-actions">
                <button
                  className="button primary"
                  disabled={saving || content.trim() === "" || content === document.content}
                  onClick={() => void save()}
                  type="button"
                >
                  {saving ? "Saving…" : "Save as new version"}
                </button>
                <button className="button secondary" disabled={saving} onClick={cancelEditing} type="button">
                  Cancel editing
                </button>
              </div>
              <p aria-live="polite" className="muted">
                {saving ? "Saving a new immutable-history version…" : "Draft changes are local until saved."}
              </p>
            </div>
          ) : (
            <pre>{document.content}</pre>
          )}
          <p className="artifact-hash">SHA-256 {document.sha256}</p>
        </article>
      </div>

      <section className="panel" aria-labelledby="provenance-heading">
        <p className="eyebrow">Approved facts only</p>
        <h2 id="provenance-heading">Claim provenance</h2>
        {provenance.length ? (
          <dl className="provenance-list">
            {provenance.map((entry, index) => (
              <div key={`${provenanceText(entry)}-${index}`}>
                <dt>{provenanceText(entry)}</dt>
                <dd>
                  {stringList(entry.evidence_ids).map((evidence) => <code key={evidence}>{evidence}</code>)}
                  {stringList(entry.source_paths).map((path) => <code key={path}>{path}</code>)}
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="form-message error" role="alert">No provenance is recorded for this material.</p>
        )}
      </section>

      <MaterialReview application={application} document={document} />
    </div>
  );
}
