import type { ApplicationState, ReadinessStatus } from "@/lib/types";
import { applicationStatus } from "@/lib/product-semantics";

type Status =
  | ReadinessStatus
  | ApplicationState
  | "ok"
  | "degraded"
  | "valid"
  | "invalid"
  | "pending"
  | "completed"
  | "cancelled";

const labels: Partial<Record<Status, string>> = {
  READY: "Ready",
  READY_WITH_WARNINGS: "Ready with warnings",
  BLOCKED: "Blocked",
  NOT_CONFIGURED: "Not configured",
  ok: "Operational",
  degraded: "Degraded",
  valid: "Valid",
  invalid: "Invalid",
};

export function StatusPill({ status }: { status: Status }) {
  const product = typeof status === "string" && status in applicationStatusesProxy ? applicationStatus(status as ApplicationState) : null;
  return (
    <span className={`status-pill ${product ? `semantic-${product.tone}` : `status-${status.toLowerCase()}`}`}>
      {product?.label ?? labels[status] ?? status.replaceAll("_", " ")}
    </span>
  );
}

const applicationStatusesProxy: Record<ApplicationState, true> = Object.fromEntries([
  "discovered","normalized","security_check","classified","scored","skipped","shortlisted","candidate_snapshot_created","materials_generating","materials_ready","review_pending","review_failed","application_started","form_filling","human_action_required","final_validation","ready_to_submit","submitting","submitted","confirmed","unknown_after_click","failed_retryable","failed_final","closed","rejected","interview","offer","withdrawn",
].map((state) => [state, true])) as Record<ApplicationState, true>;
