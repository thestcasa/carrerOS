"use client";

import { useMemo, useState } from "react";
import type { ApplicationMaterials, MaterialVersion } from "@/lib/types";

type DraftAction = "edit" | "regenerate" | "approve" | "reject";

function ReviewSummary({ material }: { material: MaterialVersion }) {
  const issues = [...material.validation.issues, ...material.review.issues];
  return (
    <section className="panel material-review" aria-labelledby="material-review-heading">
      <p className="eyebrow">Independent checks</p>
      <h2 id="material-review-heading">Validation and review</h2>
      <dl className="metadata-list">
        <div><dt>Structure</dt><dd>{material.validation.valid ? "Valid" : "Blocked"}</dd></div>
        <div><dt>Review</dt><dd>{material.review.decision.replaceAll("_", " ")}</dd></div>
        <div><dt>Claims</dt><dd>{material.review.documents_supported ? "Supported" : "Unsupported"}</dd></div>
      </dl>
      {issues.length ? (
        <ul className="review-issues">
          {issues.map((issue, index) => <li key={`${issue.code}-${index}`}><strong>{issue.severity}:</strong> {issue.message}</li>)}
        </ul>
      ) : <p className="form-message success">All deterministic checks passed.</p>}
    </section>
  );
}

export function MaterialPreview({ materials, onAction }: { materials: ApplicationMaterials; onAction?: (action: DraftAction, material: MaterialVersion) => void }) {
  const ordered = useMemo(() => [...materials.versions].sort((left, right) => right.version - left.version), [materials.versions]);
  const [selectedVersion, setSelectedVersion] = useState(ordered[0]?.version ?? 0);
  const material = ordered.find((item) => item.version === selectedVersion);

  if (!material) return <section className="empty-state"><h2>No material drafts</h2><p>Generate a draft before starting review.</p></section>;
  const immutable = material.lifecycle === "immutable";
  const canApprove = !immutable && material.validation.valid && material.review.decision === "pass";

  return (
    <div className="material-layout">
      <section className="panel action-panel" aria-labelledby="material-actions-heading">
        <div>
          <p className="eyebrow">Material workflow only</p>
          <h2 id="material-actions-heading">Draft controls</h2>
          <p className="muted">These controls review generated materials. They never authorize or submit an application.</p>
        </div>
        <div className="editor-actions">
          <button className="button secondary" disabled={immutable} onClick={() => onAction?.("edit", material)}>Edit draft</button>
          <button className="button secondary" disabled={immutable} onClick={() => onAction?.("regenerate", material)}>Regenerate</button>
          <button className="button primary" disabled={!canApprove} onClick={() => onAction?.("approve", material)}>Approve material</button>
          <button className="button secondary" disabled={immutable} onClick={() => onAction?.("reject", material)}>Reject material</button>
        </div>
      </section>

      <div className="material-grid">
        <aside className="panel version-panel" aria-labelledby="version-history-heading">
          <p className="eyebrow">Append-only history</p>
          <h2 id="version-history-heading">Version history</h2>
          <ol className="version-list">
            {ordered.map((version) => (
              <li key={version.version}>
                <button className={version.version === material.version ? "active" : ""} aria-current={version.version === material.version ? "true" : undefined} onClick={() => setSelectedVersion(version.version)}>
                  <strong>Version {version.version}</strong>
                  <span>{version.lifecycle === "immutable" ? "Immutable snapshot" : "Editable draft"}</span>
                </button>
              </li>
            ))}
          </ol>
        </aside>

        <article className="panel document-preview" aria-labelledby="document-preview-heading">
          <div className="panel-title">
            <div><p className="eyebrow">{material.kind.replaceAll("_", " ")}</p><h2 id="document-preview-heading">{materials.role} · {materials.company}</h2></div>
            <span className={`material-state ${immutable ? "immutable" : "draft"}`}>{immutable ? "Immutable snapshot" : "Editable draft"}</span>
          </div>
          <pre>{material.content}</pre>
          <p className="artifact-hash">SHA-256 {material.content_sha256}</p>
        </article>
      </div>

      <section className="panel" aria-labelledby="provenance-heading">
        <p className="eyebrow">Approved facts only</p>
        <h2 id="provenance-heading">Claim provenance</h2>
        {material.claims.length ? <dl className="provenance-list">{material.claims.map((claim, index) => <div key={`${claim.text}-${index}`}><dt>{claim.text}</dt><dd>{claim.evidence_ids.map((evidence) => <code key={evidence}>{evidence}</code>)}</dd></div>)}</dl> : <p className="form-message error" role="alert">No provenance is recorded for this material.</p>}
      </section>

      <ReviewSummary material={material} />
    </div>
  );
}
