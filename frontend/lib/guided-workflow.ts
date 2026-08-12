import type {
  ApplicationState,
  ApplicationSummary,
  HumanActionView,
  JobSummary,
  ReadinessReport,
} from "./types";

export type GuidedStageIndex = 0 | 1 | 2 | 3 | 4 | 5 | 6;

export interface GuidedWorkflowFocus {
  stage: GuidedStageIndex;
  application: ApplicationSummary | null;
  action: string | null;
  href: string | null;
  blocked: boolean;
  outcome: string | null;
}

const recordedOutcomeStates = new Set<ApplicationState>([
  "confirmed",
  "rejected",
  "interview",
  "offer",
  "withdrawn",
]);

const restartStates = new Set<ApplicationState>(["failed_final", "closed", "skipped"]);

function newestFirst(applications: ApplicationSummary[]): ApplicationSummary[] {
  return [...applications].sort((left, right) => right.updated_at.localeCompare(left.updated_at));
}

function applicationHref(candidateId: string, application: ApplicationSummary): string {
  return `/applications/${application.application_id}?candidate_id=${encodeURIComponent(candidateId)}`;
}

function focusForApplication(
  candidateId: string,
  application: ApplicationSummary,
): GuidedWorkflowFocus {
  const href = applicationHref(candidateId, application);
  switch (application.state) {
    case "review_pending":
    case "materials_ready":
      return { stage: 2, application, action: "Review the application materials", href, blocked: false, outcome: null };
    case "review_failed":
      return { stage: 2, application, action: "Fix the failed material review", href, blocked: true, outcome: null };
    case "application_started":
    case "form_filling":
    case "failed_retryable":
      return { stage: 3, application, action: "Start or check the safe dry run", href, blocked: false, outcome: null };
    case "human_action_required":
      return {
        stage: 4,
        application,
        action: "Open the human-action queue",
        href: `/actions?candidate_id=${encodeURIComponent(candidateId)}`,
        blocked: true,
        outcome: null,
      };
    case "final_validation":
    case "ready_to_submit":
      return { stage: 5, application, action: "Review the final controlled approval", href, blocked: false, outcome: null };
    case "submitting":
    case "submitted":
      return { stage: 5, application, action: "Check backend confirmation", href, blocked: true, outcome: null };
    case "unknown_after_click":
      return {
        stage: 5,
        application,
        action: "Investigate the unknown outcome — do not retry",
        href,
        blocked: true,
        outcome: null,
      };
    default:
      if (recordedOutcomeStates.has(application.state)) {
        return {
          stage: 6,
          application,
          action: "Review the recorded outcome",
          href,
          blocked: false,
          outcome: `${application.company} · ${application.role}: ${application.state.replaceAll("_", " ")}`,
        };
      }
      if (restartStates.has(application.state)) {
        return {
          stage: 1,
          application,
          action: "Choose another job",
          href: `/jobs?candidate_id=${encodeURIComponent(candidateId)}`,
          blocked: false,
          outcome: `${application.company} · ${application.role} cannot continue (${application.state.replaceAll("_", " ")}).`,
        };
      }
      return { stage: 2, application, action: "Check material preparation", href, blocked: false, outcome: null };
  }
}

export function deriveGuidedWorkflowFocus(
  candidateId: string,
  readiness: ReadinessReport,
  jobs: JobSummary[],
  applications: ApplicationSummary[],
  actions: HumanActionView[],
): GuidedWorkflowFocus {
  const encodedCandidate = encodeURIComponent(candidateId);
  if (readiness.status !== "ready") {
    return {
      stage: 0,
      application: null,
      action: "Resolve readiness blockers",
      href: `/candidates/${encodedCandidate}/readiness`,
      blocked: true,
      outcome: null,
    };
  }

  if (!jobs.length) {
    return {
      stage: 1,
      application: null,
      action: "Find and select a job",
      href: `/jobs?candidate_id=${encodedCandidate}`,
      blocked: false,
      outcome: null,
    };
  }

  const ordered = newestFirst(applications);
  const pendingAction = actions.find((action) => action.status === "pending");
  if (pendingAction) {
    const application = ordered.find(
      (item) => item.application_id === pendingAction.application_id,
    );
    if (application) {
      return {
        stage: 4,
        application,
        action: "Open the human-action queue",
        href: `/actions?candidate_id=${encodedCandidate}`,
        blocked: true,
        outcome: null,
      };
    }
  }

  const interrupted = ordered.find((item) => item.state === "unknown_after_click");
  if (interrupted) return focusForApplication(candidateId, interrupted);

  const actionable = ordered.find(
    (item) => !recordedOutcomeStates.has(item.state) && !restartStates.has(item.state),
  );
  if (actionable) return focusForApplication(candidateId, actionable);

  if (ordered.length) return focusForApplication(candidateId, ordered[0]);

  return {
    stage: 1,
    application: null,
    action: "Review a job and prepare materials",
    href: `/jobs?candidate_id=${encodedCandidate}`,
    blocked: false,
    outcome: null,
  };
}
