import type { ApplicationEventView, ApplicationState, JobRoleCategory, SettingsView } from "./types";
export type SemanticTone = "positive" | "attention" | "danger" | "info" | "neutral";
export interface ProductStatus { label: string; tone: SemanticTone; description: string }
const statuses: Record<ApplicationState, ProductStatus> = {
  discovered: { label: "Job selected", tone: "neutral", description: "The opportunity is in your workflow." },
  normalized: { label: "Checking job", tone: "info", description: "Career OS is checking the job details." },
  security_check: { label: "Safety check", tone: "info", description: "The source is being checked." },
  classified: { label: "Analyzing match", tone: "info", description: "Career OS is comparing the role with your profile." },
  scored: { label: "Match ready", tone: "positive", description: "Your match analysis is ready." },
  skipped: { label: "Not pursuing", tone: "neutral", description: "This job is no longer active." },
  shortlisted: { label: "Shortlisted", tone: "positive", description: "This job is on your shortlist." },
  candidate_snapshot_created: { label: "Profile captured", tone: "positive", description: "The application is bound to a profile version." },
  materials_generating: { label: "Preparing materials", tone: "info", description: "Your tailored documents are being prepared." },
  materials_ready: { label: "Materials ready", tone: "positive", description: "Your documents are ready to review." },
  review_pending: { label: "Needs review", tone: "attention", description: "Review the prepared application." },
  review_failed: { label: "Review blocked", tone: "danger", description: "The materials need changes." },
  application_started: { label: "Application started", tone: "info", description: "Career OS is ready to check the form." },
  form_filling: { label: "Preparing submission", tone: "info", description: "Career OS is checking the application form." },
  human_action_required: { label: "Waiting for you", tone: "attention", description: "A human-only step needs your attention." },
  final_validation: { label: "Final checks", tone: "info", description: "Career OS is running final safety checks." },
  ready_to_submit: { label: "Ready for approval", tone: "attention", description: "The application is ready for your decision." },
  submitting: { label: "Submitting", tone: "info", description: "A controlled submission is in progress." },
  submitted: { label: "Awaiting confirmation", tone: "info", description: "Submission was recorded; confirmation is still being checked." },
  confirmed: { label: "Submitted", tone: "positive", description: "The employer confirmed receipt." },
  unknown_after_click: { label: "Outcome needs review", tone: "danger", description: "Do not retry. This needs manual investigation." },
  failed_retryable: { label: "Needs another attempt", tone: "attention", description: "A safe retry may be possible." },
  failed_final: { label: "Could not submit", tone: "danger", description: "This application cannot continue automatically." },
  closed: { label: "Job closed", tone: "neutral", description: "The employer closed this opportunity." },
  rejected: { label: "Not selected", tone: "neutral", description: "The employer closed the application." },
  interview: { label: "Interview", tone: "positive", description: "The application reached interview stage." },
  offer: { label: "Offer", tone: "positive", description: "An offer has been recorded." },
  withdrawn: { label: "Withdrawn", tone: "neutral", description: "This application was withdrawn." },
};
export function applicationStatus(state: ApplicationState): ProductStatus { return statuses[state]; }
export function eventLabel(event: ApplicationEventView): string {
  const labels: Record<string, string> = { CANDIDATE_SNAPSHOT_CREATED: "Profile captured", MATERIALS_GENERATED: "Materials prepared", MATERIALS_APPROVED: "Application reviewed", BROWSER_DRY_RUN_QUEUED: "Preparing submission", BROWSER_DRY_RUN_COMPLETED: "Application form checked", HUMAN_ACTION_REQUIRED: "Waiting for you", SUBMISSION_AUTHORIZED: "Submission approved", APPLICATION_SUBMITTED: "Submitted", SUBMISSION_CONFIRMED: "Receipt confirmed" };
  return labels[event.event_type] ?? applicationStatus(event.to_state).label;
}
export function roleCategoryLabel(category: JobRoleCategory | null): string {
  if (category === "target") return "Target role";
  if (category === "adjacent") return "Adjacent role";
  if (category === "non_target") return "Outside target roles";
  return "Not classified";
}
export function matchStatus(
  score: number | null,
  category: JobRoleCategory | null,
  proposedAction?: "skip" | "review" | "prepare" | "auto_apply",
): ProductStatus {
  if (score === null) return { label: "Analysis pending", tone: "neutral", description: "Match analysis is not available yet." };
  if (category === "non_target") return { label: "Outside your targets", tone: "neutral", description: "This role is outside your configured targets." };
  if (proposedAction === "auto_apply") return { label: "Excellent match", tone: "positive", description: "This clears your configured scoring and safety thresholds; submission still requires the application workflow." };
  if (proposedAction === "prepare") return { label: "Strong match", tone: "positive", description: "This clears your configured threshold for preparing an application." };
  if (proposedAction === "review") return { label: "Possible match", tone: "attention", description: "Your scoring rules recommend human review." };
  if (proposedAction === "skip") return { label: "Weak match", tone: "neutral", description: "This does not clear your configured review threshold." };
  if (category === "target") return { label: "Target role", tone: "info", description: "This is a configured target role; review the completed analysis." };
  if (category === "adjacent") return { label: "Adjacent role", tone: "attention", description: "An adjacent role worth reviewing." };
  return { label: "Match available", tone: "info", description: "Review the evidence before deciding." };
}
export function automationStatus(settings: SettingsView, pending: number): ProductStatus {
  if (settings.emergency_stopped) return { label: "Emergency stop active", tone: "danger", description: "No new applications can be authorized." };
  if (settings.automation_mode === "disabled") return { label: "Disabled", tone: "neutral", description: "Automation is turned off." };
  if (pending > 0) return { label: "Needs attention", tone: "attention", description: "Career OS is paused on a step that needs you." };
  if (settings.automation_mode === "dry_run") return { label: "Dry run", tone: "info", description: "Career OS can test forms without submitting." };
  if (settings.automation_mode === "approval_required") return { label: "Running", tone: "positive", description: "Career OS searches and prepares; you approve final actions." };
  return { label: "Running", tone: "positive", description: "Career OS is actively searching and preparing applications." };
}
