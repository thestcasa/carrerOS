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
  | "education"
  | "experience"
  | "projects"
  | "skills"
  | "languages"
  | "career_strategy"
  | "scoring_rules"
  | "preferences"
  | "legal_status"
  | "approved_answers"
  | "cv_rules"
  | "cover_letter_rules"
  | "companies"
  | "roles";

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

export type JobWorkflowState = "discovered" | "saved" | "ignored" | "blocked" | "shortlisted";
export type JobRoleCategory = "target" | "adjacent" | "non_target";

export interface JobSummary {
  job_id: string;
  candidate_id: string;
  company: string;
  title: string;
  location: string | null;
  remote_policy: string | null;
  source: string;
  source_url: string;
  ats_platform: string | null;
  posted_at: string | null;
  verified_open_at: string | null;
  salary_display: string | null;
  role_category: JobRoleCategory | null;
  score: number | null;
  state: JobWorkflowState;
  hard_blockers: string[];
  possible_duplicate: boolean;
  stale: boolean;
}

export interface ScoreContribution {
  name: string;
  points: number;
  explanation: string;
}

export interface RequirementEvidence {
  requirement: string;
  kind: "mandatory" | "preferred";
  status: "supported" | "missing" | "ambiguous";
  evidence: string[];
}

export interface JobSecurityFinding {
  severity: "info" | "warning" | "blocking";
  code: string;
  explanation: string;
}

export interface JobDetail extends JobSummary {
  description_raw: string;
  description_normalized: string;
  source_verified: boolean;
  source_trust_level: string;
  classification_confidence: number | null;
  proposed_action: "skip" | "review" | "prepare" | "auto_apply";
  required_skills: string[];
  preferred_skills: string[];
  requirements: RequirementEvidence[];
  score_dimensions: ScoreContribution[];
  bonuses: ScoreContribution[];
  penalties: ScoreContribution[];
  salary_evidence: string | null;
  salary_confidence: number | null;
  selected_experience: string[];
  selected_projects: string[];
  security_findings: JobSecurityFinding[];
}

export type AtsPlatform = "greenhouse" | "lever" | "ashby";

export interface DiscoveryRequest {
  candidate_id: string;
  platform: AtsPlatform;
  company: string;
  company_domain: string;
  payloads: JsonObject[];
}

export interface DiscoveryResult {
  discovered: number;
  unchanged: number;
  job_ids: string[];
}

export type MaterialKind = "cv" | "cover_letter" | "answer_set";
export type MaterialLifecycle = "draft" | "immutable";

export interface MaterialClaim {
  text: string;
  evidence_ids: string[];
}

export interface MaterialValidationIssue {
  code: string;
  severity: "warning" | "error";
  message: string;
}

export interface MaterialVersion {
  version: number;
  kind: MaterialKind;
  lifecycle: MaterialLifecycle;
  created_at: string;
  content_sha256: string;
  content: string;
  claims: MaterialClaim[];
  validation: {
    valid: boolean;
    issues: MaterialValidationIssue[];
  };
  review: {
    decision: "pass" | "fail" | "human_review";
    documents_supported: boolean;
    answers_supported: boolean;
    issues: MaterialValidationIssue[];
  };
}

export interface ApplicationMaterials {
  candidate_id: string;
  application_id: string;
  company: string;
  role: string;
  versions: MaterialVersion[];
}

export type ApplicationState =
  | "discovered"
  | "normalized"
  | "security_check"
  | "classified"
  | "scored"
  | "skipped"
  | "shortlisted"
  | "candidate_snapshot_created"
  | "materials_generating"
  | "materials_ready"
  | "review_pending"
  | "review_failed"
  | "application_started"
  | "form_filling"
  | "human_action_required"
  | "final_validation"
  | "ready_to_submit"
  | "submitting"
  | "submitted"
  | "confirmed"
  | "failed_retryable"
  | "failed_final"
  | "closed"
  | "rejected"
  | "interview"
  | "offer"
  | "withdrawn";

export interface ApplicationSummary {
  application_id: string;
  candidate_id: string;
  job_id: string;
  company: string;
  role: string;
  score: number | null;
  state: ApplicationState;
  last_event: string | null;
  updated_at: string;
  next_action: string;
}

export interface ApplicationDocumentView {
  document_id: string;
  kind: "cv" | "cover_letter" | "other";
  version: number;
  content: string;
  sha256: string;
  immutable: boolean;
  validated: boolean;
  evidence_ids: string[];
  created_at: string;
}

export interface ApplicationAnswerView {
  answer_id: string;
  question_key: string;
  question: string;
  answer: string;
  supported: boolean;
  evidence_ids: string[];
}

export interface ApplicationEventView {
  event_id: string;
  event_type: string;
  from_state: ApplicationState;
  to_state: ApplicationState;
  occurred_at: string;
  payload: JsonObject;
}

export interface ApplicationDetail extends ApplicationSummary {
  source_url: string;
  ats_platform: string | null;
  documents: ApplicationDocumentView[];
  answers: ApplicationAnswerView[];
  events: ApplicationEventView[];
  review: {
    decision: "pass" | "fail" | "human_review";
    semantic_passed: boolean;
    report: JsonObject;
  } | null;
  archive_available: boolean;
  confirmation_reference: string | null;
  submitted_at: string | null;
}

export interface ArtifactView {
  artifact_id: string;
  application_id: string;
  candidate_id: string;
  kind: string;
  version: number;
  sha256: string;
  content_type: string;
  immutable: boolean;
  download_path: string;
  metadata: JsonObject;
  created_at: string;
}

export interface HumanActionView {
  action_id: string;
  candidate_id: string;
  application_id: string;
  company: string;
  role: string;
  kind: string;
  status: "pending" | "completed" | "cancelled";
  reason: string | null;
  created_at: string;
  expires_at: string | null;
  screenshot_available: boolean;
  browser_session_id: string | null;
}

export interface SecurityEventView {
  event_id: string;
  candidate_id: string;
  application_id: string | null;
  category: string;
  severity: string;
  details: JsonObject;
  resolved: boolean;
  occurred_at: string;
}

export interface SettingsView {
  candidate_id: string;
  automation_mode: "disabled" | "dry_run" | "approval_required" | "autonomous";
  discovery_enabled: boolean;
  emergency_stopped: boolean;
  allowed_ats_adapters: string[];
  tested_ats_adapters: string[];
  dry_run_acceptance_passed: boolean;
  explicit_autonomy_confirmation: boolean;
  maximum_applications_per_day: number;
  maximum_applications_per_week: number;
  maximum_applications_per_company_30_days: number;
  autonomy_blockers: string[];
}

export interface AnalyticsOverview {
  candidate_id: string;
  applications: number;
  average_score: number;
  by_state: Record<string, number>;
  by_role_category: Record<string, number>;
  human_actions_pending: number;
  security_events_unresolved: number;
  confirmations: number;
}

export interface AuthorizationView {
  authorization_id: string;
  application_id: string;
  candidate_id: string;
  workflow_state: ApplicationState;
  issued_at: string;
  expires_at: string;
}

export interface SubmissionResultView {
  application_id: string;
  state: ApplicationState;
  successful: boolean;
  status: string;
  confirmation_reference: string | null;
}
