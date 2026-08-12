import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GuidedPipeline } from "@/components/GuidedPipeline";
import type {
  ApplicationSummary,
  HumanActionView,
  JobSummary,
  ReadinessReport,
} from "@/lib/types";

const ready: ReadinessReport = {
  candidate_id: "example_candidate",
  status: "ready",
  issues: [],
  domains: [],
  capabilities: [],
};

const job: JobSummary = {
  job_id: "job-1", candidate_id: "example_candidate", external_job_id: "fixture-1",
  requisition_id: null, company: "Fictional Labs", company_domain: "fictional.invalid",
  company_stage: null, team: null, title: "ML Engineer", normalized_title: null,
  location: "Remote", normalized_location: "remote", remote_policy: "remote",
  employment_type: "full_time", seniority: null, source: "synthetic",
  source_url: "https://fictional.invalid/jobs/1", ats_platform: "greenhouse",
  posted_at: null, deadline: null, expected_start_date: null, verified_open_at: null,
  salary_display: null, salary_min: null, salary_max: null, salary_currency: null,
  salary_period: null, salary_source: null, visa_requirements: null,
  work_authorization_requirements: null, required_experience_years_min: null,
  required_experience_years_max: null, required_languages: [], role_category: "target",
  score: 90, state: "shortlisted", hard_blockers: [], possible_duplicate: false, stale: false,
};

function application(
  state: ApplicationSummary["state"],
  applicationId = "application-1",
  updatedAt = "2026-08-09T12:00:00Z",
): ApplicationSummary {
  return {
    application_id: applicationId, candidate_id: "example_candidate", job_id: job.job_id,
    company: job.company, role: job.title, score: 90, state, last_event: null,
    updated_at: updatedAt, next_action: "Continue safely",
  };
}

function pendingAction(applicationId: string): HumanActionView {
  return {
    action_id: "action-1",
    candidate_id: "example_candidate",
    application_id: applicationId,
    company: job.company,
    role: job.title,
    kind: "captcha",
    status: "pending",
    reason: "Human verification is required.",
    created_at: "2026-08-09T12:00:00Z",
    expires_at: null,
    screenshot_available: false,
    screenshot_artifact_id: null,
    screenshot_sha256: null,
    screenshot_download_path: null,
    browser_session_id: "session-1",
    session_opened: false,
    browser_session_health: "paused",
    safe_origin: "http://127.0.0.1:8090",
    takeover_capability_status: "unavailable",
    takeover_handshake_status: "ready_to_open",
    verifier_state: "awaiting_human",
    continue_available: false,
    cancel_available: true,
    continue_consequence: "Resume only after browser verification.",
    cancel_consequence: "Withdraw without submitting.",
  };
}

describe("GuidedPipeline", () => {
  it("offers exactly the readiness action while the candidate is blocked", () => {
    render(
      <GuidedPipeline
        candidateId="example_candidate"
        readiness={{ ...ready, status: "not_ready" }}
        jobs={[]}
        applications={[]}
        actions={[]}
      />,
    );

    expect(screen.getByRole("link", { name: "Resolve readiness blockers" })).toHaveAttribute(
      "href", "/candidates/example_candidate/readiness",
    );
    expect(screen.getAllByRole("link")).toHaveLength(1);
    expect(screen.getByText("Blocked")).toBeVisible();
  });

  it("moves the single action to the safe dry run from backend state", () => {
    render(
      <GuidedPipeline
        candidateId="example_candidate"
        readiness={ready}
        jobs={[job]}
        applications={[application("application_started")]}
        actions={[]}
      />,
    );

    expect(screen.getByRole("link", { name: "Start or check the safe dry run" })).toHaveAttribute(
      "href", "/applications/application-1?candidate_id=example_candidate",
    );
    expect(screen.getAllByRole("link")).toHaveLength(1);
  });

  it("surfaces the human queue before final approval", () => {
    render(
      <GuidedPipeline
        candidateId="example_candidate"
        readiness={ready}
        jobs={[job]}
        applications={[application("human_action_required")]}
        actions={[]}
      />,
    );

    expect(screen.getByRole("link", { name: "Open the human-action queue" })).toHaveAttribute(
      "href", "/actions?candidate_id=example_candidate",
    );
  });

  it("matches a pending action to its application instead of the first application", () => {
    render(
      <GuidedPipeline
        candidateId="example_candidate"
        readiness={ready}
        jobs={[job]}
        applications={[
          application("review_pending", "newer-application", "2026-08-09T13:00:00Z"),
          application("human_action_required", "paused-application", "2026-08-09T12:00:00Z"),
        ]}
        actions={[pendingAction("paused-application")]}
      />,
    );

    expect(screen.getByRole("link", { name: "Open the human-action queue" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Review the application materials" })).toBeNull();
  });

  it("never sends an unknown post-click outcome back to material review", () => {
    render(
      <GuidedPipeline
        candidateId="example_candidate"
        readiness={ready}
        jobs={[job]}
        applications={[application("unknown_after_click")]}
        actions={[]}
      />,
    );

    expect(
      screen.getByRole("link", { name: "Investigate the unknown outcome — do not retry" }),
    ).toHaveAttribute("href", "/applications/application-1?candidate_id=example_candidate");
    expect(screen.queryByRole("link", { name: "Review the application materials" })).toBeNull();
  });

  it("waits for backend confirmation instead of treating submitted as complete", () => {
    render(
      <GuidedPipeline
        candidateId="example_candidate"
        readiness={ready}
        jobs={[job]}
        applications={[application("submitted")]}
        actions={[]}
      />,
    );

    expect(screen.getByRole("link", { name: "Check backend confirmation" })).toBeVisible();
    expect(screen.queryByText(/reached a backend-recorded outcome/)).toBeNull();
  });

  it("offers another job after a terminal failure", () => {
    render(
      <GuidedPipeline
        candidateId="example_candidate"
        readiness={ready}
        jobs={[job]}
        applications={[application("failed_final")]}
        actions={[]}
      />,
    );

    expect(screen.getByRole("link", { name: "Choose another job" })).toHaveAttribute(
      "href", "/jobs?candidate_id=example_candidate",
    );
    expect(screen.getByText(/cannot continue/)).toBeVisible();
  });

  it("reports a confirmed outcome without reopening an earlier stage", () => {
    render(
      <GuidedPipeline
        candidateId="example_candidate"
        readiness={ready}
        jobs={[job]}
        applications={[application("confirmed")]}
        actions={[]}
      />,
    );

    expect(screen.getByText(/reached a backend-recorded outcome/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Review the recorded outcome" })).toHaveAttribute(
      "href", "/applications/application-1?candidate_id=example_candidate",
    );
  });
});
