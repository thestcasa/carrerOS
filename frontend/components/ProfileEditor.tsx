"use client";

import { useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { CandidateDetail, EditableSection, JsonObject, JsonValue } from "@/lib/types";

const sectionMeta: Record<EditableSection, { label: string; description: string }> = {
  identity: { label: "Identity", description: "Contact and location details used in applications." },
  biography: { label: "Biography", description: "Approved professional summary and evidence highlights." },
  career_strategy: { label: "Career strategy", description: "Target roles, domains, and candidate objectives." },
  preferences: { label: "Preferences", description: "Locations, work modes, employment types, and salary bounds." },
  legal_status: { label: "Legal status", description: "Explicit work authorization and sponsorship declarations." },
};

const sections = Object.keys(sectionMeta) as EditableSection[];

function titleFor(key: string) {
  return key.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function updateAtPath(source: JsonObject, path: string[], value: JsonValue): JsonObject {
  const result = structuredClone(source);
  let cursor: JsonObject = result;
  for (const key of path.slice(0, -1)) cursor = cursor[key] as JsonObject;
  cursor[path.at(-1)!] = value;
  return result;
}

function Field({
  fieldKey,
  path,
  value,
  onChange,
}: {
  fieldKey: string;
  path: string[];
  value: JsonValue;
  onChange: (path: string[], value: JsonValue) => void;
}) {
  const id = path.join("-");
  const label = titleFor(fieldKey);

  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    return (
      <fieldset className="nested-fields">
        <legend>{label}</legend>
        <div className="field-grid">
          {Object.entries(value).map(([nestedKey, nestedValue]) => (
            <Field key={nestedKey} fieldKey={nestedKey} path={[...path, nestedKey]} value={nestedValue} onChange={onChange} />
          ))}
        </div>
      </fieldset>
    );
  }

  if (typeof value === "boolean") {
    return (
      <label className="boolean-field" htmlFor={id}>
        <input id={id} type="checkbox" checked={value} onChange={(event) => onChange(path, event.target.checked)} />
        <span><strong>{label}</strong><small>Explicit candidate-controlled setting</small></span>
      </label>
    );
  }

  if (Array.isArray(value)) {
    return (
      <label className="form-field" htmlFor={id}>
        <span>{label}</span>
        <textarea
          id={id}
          rows={Math.max(3, value.length + 1)}
          value={value.join("\n")}
          onChange={(event) => onChange(path, event.target.value.split("\n").map((item) => item.trim()).filter(Boolean))}
        />
        <small>One value per line</small>
      </label>
    );
  }

  const isLongText = fieldKey === "summary";
  const readOnly = fieldKey === "candidate_id";
  return (
    <label className="form-field" htmlFor={id}>
      <span>{label}</span>
      {isLongText ? (
        <textarea id={id} rows={5} value={String(value ?? "")} onChange={(event) => onChange(path, event.target.value)} />
      ) : (
        <input
          id={id}
          type={typeof value === "number" ? "number" : "text"}
          value={String(value ?? "")}
          readOnly={readOnly}
          onChange={(event) => onChange(path, typeof value === "number" ? Number(event.target.value) : event.target.value)}
        />
      )}
      {readOnly ? <small>Candidate identifiers cannot be changed here.</small> : null}
    </label>
  );
}

export function ProfileEditor({ detail, initialSection = "identity" }: { detail: CandidateDetail; initialSection?: EditableSection }) {
  const safeInitial = sections.includes(initialSection) ? initialSection : "identity";
  const [activeSection, setActiveSection] = useState<EditableSection>(safeInitial);
  const sourceData = useMemo(() => structuredClone(detail.config), [detail.config]);
  const [baseline, setBaseline] = useState<Record<string, JsonObject>>(sourceData);
  const [data, setData] = useState<Record<string, JsonObject>>(sourceData);
  const [version, setVersion] = useState(detail.profile_version);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);

  const current = data[activeSection];
  const dirty = JSON.stringify(current) !== JSON.stringify(baseline[activeSection]);

  function change(path: string[], value: JsonValue) {
    setData((previous) => ({ ...previous, [activeSection]: updateAtPath(previous[activeSection], path, value) }));
    setMessage(null);
  }

  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      const result = await api.updateSection(detail.candidate_id, activeSection, current);
      setBaseline((previous) => ({ ...previous, [activeSection]: structuredClone(current) }));
      setVersion(result.profile_version);
      setMessage({ kind: "success", text: `Saved as profile version ${result.profile_version}. Previous data remains in version history.` });
    } catch (error) {
      setMessage({ kind: "error", text: error instanceof ApiError ? error.message : "The profile update failed." });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="profile-editor">
      <aside className="profile-nav" aria-label="Editable profile sections">
        <p className="eyebrow">Version {version}</p>
        {sections.map((section) => (
          <button key={section} className={activeSection === section ? "active" : ""} onClick={() => { setActiveSection(section); setMessage(null); }}>
            {sectionMeta[section].label}
          </button>
        ))}
        <p className="nav-note">Each save creates a new immutable source version.</p>
      </aside>
      <section className="editor-panel" aria-labelledby="editor-title">
        <div className="editor-header">
          <div>
            <p className="eyebrow">Candidate-controlled source data</p>
            <h2 id="editor-title">{sectionMeta[activeSection].label}</h2>
            <p>{sectionMeta[activeSection].description}</p>
          </div>
          <span className={`change-indicator ${dirty ? "changed" : ""}`}>{dirty ? "Unsaved changes" : "Saved"}</span>
        </div>
        {activeSection === "legal_status" ? (
          <div className="legal-notice" role="note">
            <strong>Submission-critical configuration.</strong> Missing or unapproved legal answers cause the deterministic submission gate to deny authorization.
          </div>
        ) : null}
        <div className="field-grid">
          {Object.entries(current).map(([key, value]) => <Field key={key} fieldKey={key} path={[key]} value={value} onChange={change} />)}
        </div>
        {message ? <p className={`form-message ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</p> : null}
        <div className="editor-actions">
          <button className="button primary" disabled={!dirty || saving} onClick={save}>{saving ? "Saving…" : "Save new version"}</button>
          <button className="button secondary" disabled={!dirty || saving} onClick={() => setData((previous) => ({ ...previous, [activeSection]: structuredClone(baseline[activeSection]) }))}>Discard changes</button>
        </div>
      </section>
    </div>
  );
}
