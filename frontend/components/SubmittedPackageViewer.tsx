"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { ArtifactView } from "@/lib/types";

const packageSlots = [
  { kind: "submitted_cv", title: "Exact submitted CV" },
  { kind: "submitted_cover_letter", title: "Exact submitted cover letter" },
  { kind: "submitted_answers", title: "Exact submitted answers" },
  { kind: "submission_receipt", title: "Final submission receipt" },
] as const;

function latestArtifact(
  artifacts: ArtifactView[],
  kind: (typeof packageSlots)[number]["kind"],
): ArtifactView | null {
  return (
    artifacts
      .filter(
        (artifact) =>
          artifact.kind === kind &&
          artifact.immutable &&
          (kind !== "submission_receipt" || artifact.version >= 2),
      )
      .sort(
        (left, right) =>
          right.version - left.version || right.created_at.localeCompare(left.created_at),
      )[0] ?? null
  );
}

function isInertText(contentType: string): boolean {
  return contentType === "application/json" || contentType === "text/html";
}

export function SubmittedPackageViewer({
  artifacts,
  applicationId,
  candidateId,
  confirmationReference,
}: {
  artifacts: ArtifactView[];
  applicationId: string;
  candidateId: string;
  confirmationReference: string | null;
}) {
  const [previews, setPreviews] = useState<Record<string, string>>({});
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scopedArtifacts = artifacts.filter(
    (artifact) =>
      artifact.application_id === applicationId && artifact.candidate_id === candidateId,
  );

  async function load(artifact: ArtifactView) {
    setLoadingId(artifact.artifact_id);
    setError(null);
    try {
      const blob = await api.downloadArtifact(candidateId, applicationId, artifact.artifact_id);
      if (isInertText(artifact.content_type)) {
        const text = await blob.text();
        setPreviews((current) => ({ ...current, [artifact.artifact_id]: text }));
        return;
      }
      if (artifact.content_type === "application/pdf") {
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `${artifact.kind}-v${artifact.version}.pdf`;
        anchor.click();
        URL.revokeObjectURL(url);
        return;
      }
      throw new Error("This submitted artifact cannot be previewed safely.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Artifact preview failed safely.");
    } finally {
      setLoadingId(null);
    }
  }

  return (
    <section className="panel" aria-labelledby="submitted-package-heading">
      <p className="eyebrow">Immutable submitted package</p>
      <h2 id="submitted-package-heading">Exact backend-confirmed submission</h2>
      {confirmationReference ? (
        <p>
          Backend confirmation <strong>{confirmationReference}</strong>
        </p>
      ) : (
        <p className="muted">
          No backend confirmation is recorded. Submitted-package artifacts remain unavailable.
        </p>
      )}
      {error ? <p className="form-message error" role="alert">{error}</p> : null}
      <div className="material-grid">
        {packageSlots.map((slot) => {
          const artifact = confirmationReference
            ? latestArtifact(scopedArtifacts, slot.kind)
            : null;
          const preview = artifact ? previews[artifact.artifact_id] : undefined;
          return (
            <article className="panel" aria-label={slot.title} key={slot.kind}>
              <h3>{slot.title}</h3>
              {artifact ? (
                <>
                  <dl className="metadata-list">
                    <div><dt>State</dt><dd>Immutable</dd></div>
                    <div><dt>Version</dt><dd>{artifact.version}</dd></div>
                    <div><dt>Content type</dt><dd>{artifact.content_type}</dd></div>
                    <div><dt>Artifact ID</dt><dd>{artifact.artifact_id}</dd></div>
                    <div><dt>SHA-256</dt><dd><code>{artifact.sha256}</code></dd></div>
                    <div><dt>Backend confirmation</dt><dd>{confirmationReference}</dd></div>
                  </dl>
                  <button
                    className="text-button"
                    disabled={loadingId === artifact.artifact_id}
                    onClick={() => void load(artifact)}
                    type="button"
                  >
                    {loadingId === artifact.artifact_id
                      ? "Loading exact artifact…"
                      : artifact.content_type === "application/pdf"
                        ? "Download exact PDF"
                        : "Preview escaped text"}
                  </button>
                  {preview !== undefined ? (
                    <pre aria-label={`${slot.title} escaped text preview`}>{preview}</pre>
                  ) : null}
                </>
              ) : (
                <p className="muted">No immutable submitted artifact is recorded.</p>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
