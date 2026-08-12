import Link from "next/link";
import type { CandidateDetail, EditableSection, JsonObject } from "@/lib/types";
import { ProductIcon } from "./ProductIcon";

const groups: Array<{ label: string; section: EditableSection; icon: "profile" | "jobs" | "document" | "sparkles" | "settings" | "shield" }> = [
  { label: "Career preferences", section: "preferences", icon: "settings" },
  { label: "Experience", section: "experience", icon: "jobs" },
  { label: "Education", section: "education", icon: "document" },
  { label: "Projects", section: "projects", icon: "sparkles" },
  { label: "Skills & technologies", section: "skills", icon: "sparkles" },
  { label: "Languages", section: "languages", icon: "profile" },
  { label: "Documents", section: "cv_rules", icon: "document" },
  { label: "Automation preferences", section: "candidate_controls", icon: "settings" },
  { label: "Privacy & data", section: "notification_rules", icon: "shield" },
];

function text(value: unknown) { return typeof value === "string" && value.trim() ? value : null; }
export function ProfileOverview({ detail }: { detail: CandidateDetail }) {
  const manifest = detail.config.manifest ?? {};
  const identity = detail.config.identity ?? {};
  const locationValue = identity.location;
  const location = (
    locationValue !== null && typeof locationValue === "object" && !Array.isArray(locationValue)
      ? locationValue
      : {}
  ) as JsonObject;
  const name = text(manifest.display_name) ?? text(identity.preferred_name) ?? text(identity.full_name) ?? detail.candidate_id;
  const place = text(locationValue) ?? text(location.display_value) ?? [text(location.city), text(location.country)].filter(Boolean).join(", ");
  const ready = detail.readiness.domains.filter((domain) => domain.status === "READY" || domain.status === "READY_WITH_WARNINGS").length;
  const total = detail.readiness.domains.length;
  const blockers = detail.readiness.issues.filter((issue) => issue.severity === "blocking").length;
  return <>
    <section className="profile-summary-card">
      <span className="profile-avatar">{name.split(" ").map((part) => part[0]).join("").slice(0, 2).toUpperCase()}</span>
      <div><h2>{name}</h2>{place ? <p>{place}</p> : null}<p className="muted">Profile version {detail.profile_version}</p></div>
    </section>
    <section className="profile-readiness-card" aria-labelledby="profile-readiness-title">
      <div className="profile-readiness-head"><div><p className="card-kicker">Profile readiness</p><h2 id="profile-readiness-title">{ready} of {total} sections ready</h2></div><strong>{blockers}</strong></div>
      <div className="readiness-progress" aria-label={`${ready} of ${total} profile sections ready`}><span style={{ width: `${total ? Math.round((ready / total) * 100) : 0}%` }} /></div>
      <p>{blockers ? `${blockers} ${blockers === 1 ? "item needs" : "items need"} your review.` : "Your profile has no blocking readiness items."}</p>
      <Link className="card-link" href={`/candidates/${detail.candidate_id}/readiness`}>Review profile readiness <ProductIcon name="chevron" /></Link>
    </section>
    <nav className="profile-section-list" aria-label="Profile sections">
      {groups.map((group) => <Link key={group.section} href={`/candidates/${detail.candidate_id}/profile?section=${group.section}#profile-editor`}><span className="settings-row-icon"><ProductIcon name={group.icon} /></span><span>{group.label}</span><ProductIcon name="chevron" /></Link>)}
    </nav>
  </>;
}
