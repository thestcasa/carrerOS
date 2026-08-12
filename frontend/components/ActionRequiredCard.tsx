import Link from "next/link";
import type { HumanActionView } from "@/lib/types";
import { ProductIcon } from "./ProductIcon";

function actionTitle(action: HumanActionView) {
  const kind = action.kind.toLowerCase();
  if (kind.includes("captcha")) return "CAPTCHA requires you";
  if (kind.includes("otp")) return "Enter your verification code";
  if (kind.includes("legal")) return "Review a legal question";
  if (kind.includes("answer") || kind.includes("question")) return "Answer an application question";
  return action.reason || "Review this application";
}

export function ActionRequiredCard({ candidateId, action }: { candidateId: string; action: HumanActionView }) {
  return (
    <article className="attention-card">
      <span className="attention-icon"><ProductIcon name={action.kind.toLowerCase().includes("captcha") ? "shield" : "warning"} /></span>
      <div>
        <p className="attention-company">{action.company} · {action.role}</p>
        <h3>{actionTitle(action)}</h3>
        <p className="muted">{new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(action.created_at))}</p>
      </div>
      <Link href={`/actions?candidate_id=${encodeURIComponent(candidateId)}`} aria-label={`Open action for ${action.role} at ${action.company}`}><ProductIcon name="chevron" /></Link>
    </article>
  );
}
