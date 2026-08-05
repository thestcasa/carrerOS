import type { ApplicationState, ReadinessStatus } from "@/lib/types";

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
  return (
    <span className={`status-pill status-${status.toLowerCase()}`}>
      {labels[status] ?? status.replaceAll("_", " ")}
    </span>
  );
}
