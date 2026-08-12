"use client";

import { useMemo, useRef, useState } from "react";
import { TagEditor } from "./TagEditor";
import { api, ApiError } from "@/lib/api";
import type {
  CandidateDetail,
  CandidateManifestControlsUpdate,
  EditableSection,
  JsonObject,
  JsonValue,
} from "@/lib/types";

const sectionMeta: Record<EditableSection, { label: string; description: string }> = {
  candidate_controls: { label: "Readiness approvals", description: "Approve the complete profile and choose candidate-level workflow boundaries." },
  identity: { label: "Identity", description: "Contact and location details used in applications." },
  biography: { label: "Biography", description: "Approved professional summary and evidence highlights." },
  education: { label: "Education", description: "Qualifications with stable IDs and verified dates." },
  experience: { label: "Experience", description: "Professional evidence, achievements, dates, and skills." },
  projects: { label: "Projects", description: "Candidate-owned project evidence and outcomes." },
  skills: { label: "Skills", description: "Evidence-backed skill categories." },
  languages: { label: "Languages", description: "Explicit candidate-approved proficiency levels." },
  career_strategy: { label: "Career strategy", description: "Target roles, domains, and candidate objectives." },
  scoring_rules: { label: "Scoring rules", description: "Candidate-specific thresholds and dimension weights." },
  preferences: { label: "Preferences", description: "Locations, work modes, employment types, and salary bounds." },
  legal_status: { label: "Legal status", description: "Explicit work authorization and sponsorship declarations." },
  approved_answers: { label: "Approved answers", description: "Reusable answers that remain evidence-bound." },
  cv_rules: { label: "CV rules", description: "Candidate-controlled document limits and prohibited claims." },
  cover_letter_rules: { label: "Cover letter rules", description: "Candidate-controlled generation policy." },
  companies: { label: "Company rules", description: "Target and blocked companies." },
  roles: { label: "Role rules", description: "Target and blocked roles." },
  certifications: { label: "Certifications", description: "Approved credentials with stable IDs, dates, and evidence links." },
  publications: { label: "Publications", description: "Candidate-approved publications and public summaries." },
  notification_rules: { label: "Notifications", description: "Secret-free event, channel, and digest preferences." },
};

const sections = Object.keys(sectionMeta) as EditableSection[];

const structuredTemplates: Partial<Record<EditableSection, Record<string, JsonObject>>> = {
  education: { items: { id: "new_education", institution: "", qualification: "", field_of_study: "", location: "", start_date: "", end_date: null, completed: false, grade: null, coursework: [], cv_eligible: true, approved: false, archived: false } },
  experience: {
    items: { id: "new_experience", organization: "", title: "", location: "", start_date: "", end_date: null, current: true, achievements: [], skills: [], employment_type: null, remote_policy: "unknown", summary: null, responsibilities: [], domains: [], role_categories: [], confidentiality: "restricted", cv_eligible: true, cover_letter_eligible: true, approved: false, archived: false },
    achievements: { id: "new_claim", statement: "", verified: false, source: null, publicly_usable: false, confidentiality: "restricted", approved: false, archived: false },
  },
  projects: {
    items: { id: "new_project", name: "", description: "", start_date: "", end_date: null, outcomes: [], skills: [], url: null, project_type: null, status: "completed", domains: [], role_categories: [], evidence: [], confidentiality: "restricted", public_summary: null, cv_eligible: true, cover_letter_eligible: true, interview_eligible: true, approved: false, archived: false },
    outcomes: { id: "new_claim", statement: "", verified: false, source: null, publicly_usable: false, confidentiality: "restricted", approved: false, archived: false },
  },
  languages: { items: { language: "", level: "B2", professional_use: false, approved: false, archived: false } },
  career_strategy: { role_tiers: { tier: 1, name: "", roles: [], application_share_target: 0 } },
  approved_answers: { items: { key: "new_answer", question_pattern: "", answer: "", evidence_ids: [], question_categories: [], approved: false, sensitive: false, auto_submit_allowed: false, valid_from: null, valid_until: null, archived: false } },
  cover_letter_rules: { motivations: { motivation_id: "new_motivation", text: "", companies: [], roles: [], approved: false } },
  certifications: { items: { id: "new_certification", name: "", issuer: "", issued_date: null, expiration_date: null, credential_url: null, cv_eligible: true, approved: false, archived: false } },
  publications: { items: { id: "new_publication", title: "", publisher: null, published_date: null, url: null, summary: null, cv_eligible: true, approved: false, archived: false } },
};

function candidateControls(detail: CandidateDetail): JsonObject {
  const manifest = detail.config.manifest ?? {};
  const workflow = manifest.workflow;
  const validation = manifest.validation;
  return {
    validation: validation && typeof validation === "object" && !Array.isArray(validation)
      ? structuredClone(validation)
      : {
          profile_approved: false,
          legal_status_approved: false,
          automatic_answers_approved: false,
          cv_templates_approved: false,
        },
    workflow: workflow && typeof workflow === "object" && !Array.isArray(workflow)
      ? structuredClone(workflow)
      : {
          discovery_enabled: false,
          automatic_submission_enabled: false,
          email_tracking_enabled: false,
          notifications_enabled: true,
        },
    acknowledge_automatic_submission_consequences: false,
  };
}

function controlsPayload(data: JsonObject): CandidateManifestControlsUpdate {
  const workflow = data.workflow as JsonObject;
  const validation = data.validation as JsonObject;
  return {
    workflow: {
      discovery_enabled: workflow.discovery_enabled === true,
      automatic_submission_enabled: workflow.automatic_submission_enabled === true,
      email_tracking_enabled: workflow.email_tracking_enabled === true,
      notifications_enabled: workflow.notifications_enabled === true,
    },
    validation: {
      profile_approved: validation.profile_approved === true,
      legal_status_approved: validation.legal_status_approved === true,
      automatic_answers_approved: validation.automatic_answers_approved === true,
      cv_templates_approved: validation.cv_templates_approved === true,
    },
    acknowledge_automatic_submission_consequences:
      data.acknowledge_automatic_submission_consequences === true,
  };
}

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
  arrayTemplate,
}: {
  fieldKey: string;
  path: string[];
  value: JsonValue;
  onChange: (path: string[], value: JsonValue) => void;
  arrayTemplate: (path: string[]) => JsonObject | undefined;
}) {
  const id = path.join("-");
  const label = titleFor(fieldKey);

  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    return (
      <fieldset className="nested-fields">
        <legend>{label}</legend>
        <div className="field-grid">
          {Object.entries(value).map(([nestedKey, nestedValue]) => (
            <Field key={nestedKey} fieldKey={nestedKey} path={[...path, nestedKey]} value={nestedValue} onChange={onChange} arrayTemplate={arrayTemplate} />
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
    const template = arrayTemplate(path);
    const structured = Boolean(template) || value.some((item) => item !== null && typeof item === "object");
    if (structured) return <StructuredArrayField label={label} path={path} value={value} onChange={onChange} emptyTemplate={template} arrayTemplate={arrayTemplate} />;
    return <TagEditor id={id} label={label} values={value.filter((item): item is string => typeof item === "string")} onChange={(values) => onChange(path, values)} />;
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

function blankFromTemplate(value: JsonValue, key = ""): JsonValue {
  if (Array.isArray(value)) return [];
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([nestedKey, nestedValue]) => [
        nestedKey,
        blankFromTemplate(nestedValue, nestedKey),
      ]),
    );
  }
  if (key === "id" || key === "key" || key.endsWith("_id")) return `new_${globalThis.crypto?.randomUUID?.() ?? Date.now()}`;
  if (typeof value === "boolean") return false;
  if (typeof value === "number") return 0;
  if (typeof value === "string") return "";
  return null;
}

function StructuredArrayField({ label, path, value, onChange, emptyTemplate, arrayTemplate }: {
  label: string;
  path: string[];
  value: JsonValue[];
  onChange: (path: string[], value: JsonValue) => void;
  emptyTemplate: JsonObject | undefined;
  arrayTemplate: (path: string[]) => JsonObject | undefined;
}) {
  const template = value.find(
    (item): item is JsonObject => item !== null && typeof item === "object" && !Array.isArray(item),
  ) ?? emptyTemplate;

  function replace(index: number, item: JsonValue) {
    onChange(path, value.map((current, itemIndex) => itemIndex === index ? item : current));
  }

  function move(index: number, offset: number) {
    const destination = index + offset;
    if (destination < 0 || destination >= value.length) return;
    const next = [...value];
    [next[index], next[destination]] = [next[destination], next[index]];
    onChange(path, next);
  }

  return (
    <fieldset className="structured-list">
      <legend>{label}</legend>
      {value.length === 0 ? <p className="muted">No entries yet.</p> : null}
      {value.map((item, index) => {
        if (item === null || typeof item !== "object" || Array.isArray(item)) return null;
        const itemName = String(item.name ?? item.title ?? item.organization ?? item.language ?? item.id ?? `Entry ${index + 1}`);
        return (
          <article className="structured-entry" key={String(item.id ?? `${path.join("-")}-${index}`)} aria-label={`${label}: ${itemName}`}>
            <div className="structured-entry-header">
              <div><strong>{itemName || `Entry ${index + 1}`}</strong><small>Entry {index + 1} of {value.length}</small></div>
              <div className="inline-actions">
                <button type="button" className="button subtle" disabled={index === 0} onClick={() => move(index, -1)} aria-label={`Move ${itemName} up`}>Move up</button>
                <button type="button" className="button subtle" disabled={index === value.length - 1} onClick={() => move(index, 1)} aria-label={`Move ${itemName} down`}>Move down</button>
                {typeof item.archived === "boolean" ? (
                  <button type="button" className="button secondary" onClick={() => replace(index, { ...item, archived: !item.archived })}>
                    {item.archived ? "Restore entry" : "Archive entry"}
                  </button>
                ) : null}
              </div>
            </div>
            <div className="field-grid compact">
              {Object.entries(item).map(([nestedKey, nestedValue]) => (
                <Field
                  key={nestedKey}
                  fieldKey={nestedKey}
                  path={[nestedKey]}
                  value={nestedValue}
                  arrayTemplate={arrayTemplate}
                  onChange={(nestedPath, nestedValueNext) => replace(
                    index,
                    updateAtPath(item, nestedPath, nestedValueNext),
                  )}
                />
              ))}
            </div>
          </article>
        );
      })}
      {template ? (
        <button type="button" className="button secondary" onClick={() => onChange(path, [...value, blankFromTemplate(template)])}>
          Add {label.toLowerCase().replace(/s$/, "")}
        </button>
      ) : (
        <small>Add the first entry through an import or fixture so its schema can be preserved safely.</small>
      )}
    </fieldset>
  );
}

export function ProfileEditor({ detail, initialSection = "identity" }: { detail: CandidateDetail; initialSection?: EditableSection }) {
  const safeInitial = sections.includes(initialSection) ? initialSection : "identity";
  const [activeSection, setActiveSection] = useState<EditableSection>(safeInitial);
  const sourceData = useMemo(
    () => ({ ...structuredClone(detail.config), candidate_controls: candidateControls(detail) }),
    [detail],
  );
  const [baseline, setBaseline] = useState<Record<string, JsonObject>>(sourceData);
  const [data, setData] = useState<Record<string, JsonObject>>(sourceData);
  const [version, setVersion] = useState(detail.profile_version);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const saveCommand = useRef<{ identity: string; key: string } | null>(null);

  const current = data[activeSection] ?? {};
  const dirty = JSON.stringify(current) !== JSON.stringify(baseline[activeSection] ?? {});

  function change(path: string[], value: JsonValue) {
    setData((previous) => ({ ...previous, [activeSection]: updateAtPath(previous[activeSection] ?? {}, path, value) }));
    setMessage(null);
  }

  function arrayTemplate(path: string[]): JsonObject | undefined {
    const templates = structuredTemplates[activeSection];
    return templates?.[path.at(-1) ?? ""];
  }

  async function save() {
    setSaving(true);
    setMessage(null);
    const identity = JSON.stringify({
      candidateId: detail.candidate_id,
      section: activeSection,
      data: current,
    });
    if (saveCommand.current?.identity !== identity) {
      saveCommand.current = {
        identity,
        key: `update-profile-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`,
      };
    }
    try {
      const result = activeSection === "candidate_controls"
        ? await api.updateCandidateControls(
            detail.candidate_id,
            controlsPayload(current),
            saveCommand.current.key,
          )
        : await api.updateSection(
            detail.candidate_id,
            activeSection,
            current,
            saveCommand.current.key,
          );
      saveCommand.current = null;
      const saved = activeSection === "candidate_controls"
        ? { ...structuredClone(current), acknowledge_automatic_submission_consequences: false }
        : structuredClone(current);
      setBaseline((previous) => ({ ...previous, [activeSection]: saved }));
      setData((previous) => ({ ...previous, [activeSection]: structuredClone(saved) }));
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
        {activeSection === "candidate_controls" ? (
          <div className="legal-notice" role="note">
            <strong>Candidate-controlled safety boundary.</strong> Approve these controls only
            after reviewing the underlying sections. Allowing submission workflows does not enable
            autonomous mode, confirm autonomy, or bypass manual approval and SubmissionGate.
          </div>
        ) : null}
        <div className="field-grid">
          {Object.entries(current).map(([key, value]) => <Field key={key} fieldKey={key} path={[key]} value={value} onChange={change} arrayTemplate={arrayTemplate} />)}
        </div>
        {message ? <p className={`form-message ${message.kind}`} role={message.kind === "error" ? "alert" : "status"}>{message.text}</p> : null}
        <div className="editor-actions">
          <button className="button primary" disabled={!dirty || saving} onClick={save}>{saving ? "Saving…" : "Save new version"}</button>
          <button className="button secondary" disabled={!dirty || saving} onClick={() => setData((previous) => ({ ...previous, [activeSection]: structuredClone(baseline[activeSection] ?? {}) }))}>Discard changes</button>
        </div>
      </section>
    </div>
  );
}
