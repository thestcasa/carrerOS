"use client";

import { useRef, useState } from "react";
import { api } from "@/lib/api";
import type { CandidateDetail, CVImportDraft } from "@/lib/types";

async function fileAsBase64(file: File): Promise<string> {
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("The selected CV could not be read."));
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string" || !result.includes(",")) {
        reject(new Error("The selected CV could not be encoded."));
        return;
      }
      resolve(result.slice(result.indexOf(",") + 1));
    };
    reader.readAsDataURL(file);
  });
}

export function CVImportPanel({
  candidateId,
  onApplied,
}: {
  candidateId: string;
  onApplied: (detail: CandidateDetail) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [draft, setDraft] = useState<CVImportDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const extractCommand = useRef<{ identity: string; key: string } | null>(null);
  const applyCommand = useRef<{ identity: string; key: string } | null>(null);

  async function extract() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const content = await fileAsBase64(file);
      const identity = `${candidateId}:${file.name}:${file.size}:${file.lastModified}`;
      if (extractCommand.current?.identity !== identity) {
        extractCommand.current = {
          identity,
          key: `create-cv-import-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`,
        };
      }
      setDraft(
        await api.createCvImport(
          candidateId,
          file.name,
          content,
          extractCommand.current.key,
        ),
      );
      extractCommand.current = null;
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "CV extraction failed safely.");
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    if (!draft) return;
    setBusy(true);
    setError(null);
    const identity = `${candidateId}:${draft.import_id}`;
    if (applyCommand.current?.identity !== identity) {
      applyCommand.current = {
        identity,
        key: `apply-cv-import-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`,
      };
    }
    try {
      onApplied(
        await api.applyCvImport(
          candidateId,
          draft.import_id,
          applyCommand.current.key,
        ),
      );
      applyCommand.current = null;
      setDraft(null);
      setFile(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "CV import could not be applied.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <div className="panel-title">
        <div>
          <p className="eyebrow">Portable onboarding</p>
          <h2>Import a CV draft</h2>
        </div>
      </div>
      <p>
        Bounded TXT, PDF, and DOCX text is extracted locally. The source file is not retained, and
        every imported fact remains restricted and unapproved until you review it. Encrypted,
        active-content, oversized, or excessively compressed documents fail closed.
      </p>
      <label className="form-field">
        <span>CV file</span>
        <input
          aria-label="CV file"
          accept=".txt,.pdf,.docx,text/plain,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          type="file"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
            setDraft(null);
            extractCommand.current = null;
            applyCommand.current = null;
          }}
        />
      </label>
      <button className="button secondary" disabled={!file || busy} onClick={() => void extract()}>
        {busy ? "Checking…" : "Extract unapproved draft"}
      </button>
      {error ? <p role="alert">{error}</p> : null}
      {draft ? (
        <div className="callout warning">
          <p>
            Detected {draft.education.items.length} education and {draft.experience.items.length}{" "}
            experience entries. Approval is still required.
          </p>
          <ul>{draft.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
          <button
            className="button primary"
            disabled={busy || draft.education.items.length + draft.experience.items.length === 0}
            onClick={() => void apply()}
          >
            Apply as unapproved facts
          </button>
        </div>
      ) : null}
    </section>
  );
}
