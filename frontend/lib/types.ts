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
  | "roles"
  | "certifications"
  | "publications"
  | "notification_rules";

export interface CandidateUpdateResult {
  candidate_id: string;
  previous_version: string;
  profile_version: string;
  section: EditableSection;
  readiness: ReadinessReport;
}

export type CandidateConfigurationFormat = "json" | "yaml";

export interface CandidateConfigurationImportInput {
  format: CandidateConfigurationFormat;
  content: string;
  expected_profile_version: string;
}

export interface CandidateConfigurationImportResult {
  candidate_id: string;
  previous_version: string;
  profile_version: string;
  source_profile_version: string;
  source_sha256: string;
  changed: boolean;
  imported_sections: EditableSection[];
  readiness: ReadinessReport;
}

export interface CandidateDeletionView {
  candidate_id: string;
  status: "deleting" | "failed" | "completed";
  deleted_rows: Record<string, number>;
  deleted_paths: string[];
  error_code: string | null;
  requested_at: string;
  completed_at: string | null;
}

export interface CandidateExportView extends JsonObject {
  schema_version: "1.0";
  candidate_id: string;
  created_at: string;
  files: Array<{
    path: string;
    size: number;
    sha256: string;
    content_base64: string;
  }>;
  database: Record<string, JsonObject[]>;
  manifest_sha256: string;
}

export interface CVImportDraft {
  import_id: string;
  candidate_id: string;
  source_filename: string;
  source_sha256: string;
  education: { items: JsonObject[] };
  experience: { items: JsonObject[] };
  warnings: string[];
  approval_required: true;
  applied_profile_version: string | null;
}

export interface ApiErrorBody {
  error?: { code?: string; message?: string };
}

export type JobWorkflowState = "discovered" | "saved" | "ignored" | "blocked" | "shortlisted";
export type JobRoleCategory = "target" | "adjacent" | "non_target";

export interface RequiredJobLanguage {
  language: string;
  minimum_level: "A1" | "A2" | "B1" | "B2" | "C1" | "C2" | "native" | null;
}

export interface JobSummary {
  job_id: string;
  candidate_id: string;
  external_job_id: string;
  requisition_id: string | null;
  company: string;
  company_domain: string | null;
  company_stage: string | null;
  team: string | null;
  title: string;
  normalized_title: string | null;
  location: string | null;
  normalized_location: string | null;
  remote_policy: string | null;
  employment_type: string | null;
  seniority: string | null;
  source: string;
  source_url: string;
  ats_platform: string | null;
  posted_at: string | null;
  deadline: string | null;
  expected_start_date: string | null;
  verified_open_at: string | null;
  salary_display: string | null;
  salary_min: string | null;
  salary_max: string | null;
  salary_currency: string | null;
  salary_period: string | null;
  salary_source: string | null;
  visa_requirements: string | null;
  work_authorization_requirements: string | null;
  required_experience_years_min: number | null;
  required_experience_years_max: number | null;
  required_languages: RequiredJobLanguage[];
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
  changed_job_ids?: string[];
}

export interface DiscoverySourceView {
  source_id: string;
  candidate_id: string;
  provider: AtsPlatform;
  company: string;
  company_domain: string;
  board_token: string;
  enabled: boolean;
  cadence_minutes: number;
  next_run_at: string;
  last_success_at: string | null;
  last_error: string | null;
  last_status: string | null;
  last_discovered: number;
  last_unchanged: number;
}

export interface DiscoverySourceCreate {
  provider: AtsPlatform;
  company: string;
  company_domain: string;
  board_token: string;
  cadence_minutes: number;
  enabled: boolean;
}

export interface DiscoverySourceUpdate {
  enabled?: boolean;
  cadence_minutes?: number;
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
  | "unknown_after_click"
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
  provenance: JsonObject[];
  revision_actor: string | null;
  base_document_id: string | null;
  render_metadata: JsonObject;
}

export interface MaterialRevisionInput {
  document_id: string;
  base_version: number;
  content: string;
  reason?: string;
}

export interface AnswerRevisionInput {
  answer_id: string;
  base_version: number;
  answer: string;
  reason?: string;
}

export interface ApplicationAnswerView {
  answer_id: string;
  question_key: string;
  question: string;
  answer: string;
  version: number;
  sha256: string;
  immutable: boolean;
  revision_kind: "generated" | "manual" | "withdrawn" | "legacy_unknown";
  revision_actor: string;
  base_answer_id: string | null;
  reason: string | null;
  approved_source_key: string | null;
  candidate_snapshot_id: string | null;
  candidate_snapshot_version: string | null;
  candidate_snapshot_sha256: string | null;
  supported: boolean;
  evidence_ids: string[];
  created_at: string;
}

export interface ApplicationEventView {
  event_id: string;
  event_type: string;
  from_state: ApplicationState;
  to_state: ApplicationState;
  occurred_at: string;
  payload: JsonObject;
}

export interface MaterialPolicy {
  schema_version: "1.0";
  generator_version: "deterministic_material_v2" | "legacy_material_unknown";
  job_version: number;
  job_payload_sha256: string;
  cv_template_id: string;
  cv_template_version: string;
  selected_experience_ids: string[];
  selected_project_ids: string[];
  cover_letter: {
    included: boolean;
    reason: string | null;
    selected_experience_ids: string[];
    selected_project_ids: string[];
    minimum_words: number;
    maximum_words: number;
  };
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
  correspondence: CorrespondenceView[];
  archive_available: boolean;
  confirmation_reference: string | null;
  submitted_at: string | null;
  material_policy: MaterialPolicy | null;
}

export interface ControlledSubmissionExecutionView {
  attempt_id: string;
  application_id: string;
  candidate_id: string;
  authorization_id: string;
  task_id: string | null;
  adapter: "greenhouse_controlled_v1";
  status:
    | "prepared"
    | "click_authorized"
    | "confirmed"
    | "confirmation_missing"
    | "unknown_after_click"
    | "denied";
  application_state: ApplicationState;
  successful: boolean;
  retryable: false;
  confirmation_reference: string | null;
  click_boundary_entered_at: string | null;
  finalized_at: string | null;
}

export interface CorrespondenceView {
  correspondence_id: string;
  candidate_id: string;
  application_id: string | null;
  provider_message_id: string;
  kind: string;
  sender: string;
  subject: string;
  received_at: string;
  association_reason: string;
}

export interface NotificationView {
  notification_id: string;
  candidate_id: string;
  application_id: string | null;
  event_type: string;
  channel: string;
  message: string;
  immediate: boolean;
  status: string;
  created_at: string;
}

export interface InterviewPreparationPackage extends JsonObject {
  candidate_id: string;
  application_id: string;
  company: string;
  job_title: string;
  source_artifacts_sha256: string;
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
  screenshot_artifact_id: string | null;
  screenshot_sha256: string | null;
  screenshot_download_path: string | null;
  browser_session_id: string | null;
  session_opened: boolean;
  browser_session_health: "unavailable" | "paused" | "takeover_opened" | "resuming" | "ready" | "failed" | "closed" | "expired";
  safe_origin: string | null;
  takeover_capability_status: "unavailable" | "not_required";
  takeover_handshake_status: "unavailable" | "ready_to_open" | "opened" | "closed" | "expired" | "not_required";
  verifier_state: "not_required" | "awaiting_human" | "awaiting_browser_verification" | "verified" | "cancelled" | "expired" | "unavailable";
  continue_available: boolean;
  cancel_available: boolean;
  continue_consequence: string;
  cancel_consequence: string;
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
  allowed_ats_adapters: AtsPlatform[];
  tested_ats_adapters: AtsPlatform[];
  dry_run_acceptance_passed: boolean;
  explicit_autonomy_confirmation: boolean;
  maximum_applications_per_day: number;
  maximum_applications_per_week: number;
  maximum_applications_per_company_30_days: number;
  browser_session_retention_days: number;
  autonomy_blockers: string[];
  autonomy_prerequisites: AutonomyPrerequisiteView[];
  controlled_submission_enabled?: boolean;
}

export interface AutonomyPrerequisiteView {
  code: string;
  title: string;
  explanation: string;
  passed: boolean;
  resolution: string;
  action_href: string;
  evidence_id: string | null;
  evidence_summary: string | null;
  evidenced_at: string | null;
}

export interface SettingsUpdate {
  candidate_id: string;
  automation_mode?: SettingsView["automation_mode"];
  discovery_enabled?: boolean;
  allowed_ats_adapters?: AtsPlatform[];
  maximum_applications_per_day?: number;
  maximum_applications_per_week?: number;
  maximum_applications_per_company_30_days?: number;
  browser_session_retention_days?: number;
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
