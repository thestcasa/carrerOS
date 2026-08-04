export type ReadinessStatus =
  | "READY"
  | "READY_WITH_WARNINGS"
  | "BLOCKED"
  | "NOT_CONFIGURED";

export interface ServiceStatus {
  status: "available" | "unavailable";
  detail: string | null;
}

export interface HealthReport {
  status: "ok" | "degraded";
  api: ServiceStatus;
  database: ServiceStatus;
  redis: ServiceStatus;
}

export interface CandidateSummary {
  candidate_id: string;
  display_name: string;
  profile_version: string | null;
  configuration_status: "valid" | "invalid";
  readiness_status: "ready" | "not_ready" | "invalid";
  automation_status: "disabled" | "autonomous" | "unknown";
}

export interface ReadinessIssue {
  code: string;
  message: string;
  domain: string;
  field_path: string;
  severity: "warning" | "blocking";
}

export interface DomainReadiness {
  domain: string;
  label: string;
  status: ReadinessStatus;
  field_path: string;
  issues: ReadinessIssue[];
}

export interface CapabilityReadiness {
  capability: string;
  label: string;
  status: ReadinessStatus;
  blockers: string[];
}

export interface ReadinessReport {
  candidate_id: string;
  status: "ready" | "not_ready";
  issues: ReadinessIssue[];
  domains: DomainReadiness[];
  capabilities: CapabilityReadiness[];
}

export type JsonValue = string | number | boolean | null | JsonValue[] | JsonObject;
export interface JsonObject {
  [key: string]: JsonValue;
}

export interface CandidateDetail {
  candidate_id: string;
  profile_version: string;
  config: Record<string, JsonObject>;
  readiness: ReadinessReport;
}

export type EditableSection =
  | "identity"
  | "biography"
  | "career_strategy"
  | "preferences"
  | "legal_status";

export interface CandidateUpdateResult {
  candidate_id: string;
  previous_version: string;
  profile_version: string;
  section: EditableSection;
  readiness: ReadinessReport;
}

export interface ApiErrorBody {
  error?: { code?: string; message?: string };
}
