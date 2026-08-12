"use client";
import { useState } from "react";
import { ProductIcon } from "./ProductIcon";
export function TagEditor({ id, label, values, onChange }: { id: string; label: string; values: string[]; onChange: (values: string[]) => void }) {
  const [draft, setDraft] = useState("");
  function add() {
    const value = draft.trim();
    if (!value || values.includes(value)) return;
    onChange([...values, value]);
    setDraft("");
  }
  return <div className="tag-editor">
    <span className="tag-editor-label">{label}</span>
    <div className="tag-list">{values.map((value) => <span className="tag-chip" key={value}>{value}<button type="button" onClick={() => onChange(values.filter((item) => item !== value))} aria-label={`Remove ${value}`}><ProductIcon name="close" /></button></span>)}</div>
    <div className="tag-input-row">
      <label className="sr-only" htmlFor={id}>Add {label.toLowerCase()}</label>
      <input id={id} value={draft} placeholder={`Add ${label.toLowerCase()}`} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === ",") { event.preventDefault(); add(); }
        if (event.key === "Backspace" && !draft && values.length) onChange(values.slice(0, -1));
      }} />
      <button className="button secondary" type="button" onClick={add} disabled={!draft.trim()}>Add</button>
    </div>
    <small>Press Enter to add a value. Changes are saved only when you save the profile version.</small>
  </div>;
}
