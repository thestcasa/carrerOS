import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GuidedPipeline } from "@/components/GuidedPipeline";
import type { ApplicationSummary, JobSummary, ReadinessReport } from "@/lib/types";

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

function application(state: ApplicationSummary["state"]): ApplicationSummary {
  return {
    application_id: "application-1", candidate_id: "example_candidate", job_id: job.job_id,
    company: job.company, role: job.title, score: 90, state, last_event: null,
    updated_at: "2026-08-09T12:00:00Z", next_action: "Continue safely",
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
});
