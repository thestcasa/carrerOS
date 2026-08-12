import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { JobsInbox } from "@/components/JobsInbox";
import type { JobSummary } from "@/lib/types";

const jobs: JobSummary[] = [
  { job_id: "job-1", candidate_id: "example_candidate", external_job_id: "gh-1", requisition_id: "REQ-1", company: "Fictional Labs", company_domain: "fictional.invalid", company_stage: "scaleup", team: "AI", title: "ML Engineer", normalized_title: "machine learning engineer", location: "Remote", normalized_location: "remote", remote_policy: "remote", employment_type: "full_time", seniority: "early_career", source: "official", source_url: "https://jobs.example.invalid/1", ats_platform: "greenhouse", posted_at: "2026-08-01", deadline: null, expected_start_date: "2027-01-01", verified_open_at: "2026-08-04", salary_display: null, salary_min: null, salary_max: null, salary_currency: null, salary_period: null, salary_source: null, visa_requirements: null, work_authorization_requirements: null, required_experience_years_min: null, required_experience_years_max: null, required_languages: [], role_category: "target", score: 87, state: "shortlisted", hard_blockers: [], possible_duplicate: false, stale: false },
  { job_id: "job-2", candidate_id: "example_candidate", external_job_id: "lever-2", requisition_id: null, company: "Example Systems", company_domain: "example.invalid", company_stage: null, team: null, title: "Senior Analyst", normalized_title: "senior analyst", location: "Paris", normalized_location: "paris", remote_policy: "onsite", employment_type: null, seniority: "senior", source: "official", source_url: "https://jobs.example.invalid/2", ats_platform: "lever", posted_at: null, deadline: null, expected_start_date: null, verified_open_at: null, salary_display: null, salary_min: null, salary_max: null, salary_currency: null, salary_period: null, salary_source: null, visa_requirements: null, work_authorization_requirements: null, required_experience_years_min: 5, required_experience_years_max: null, required_languages: [], role_category: "non_target", score: 40, state: "blocked", hard_blockers: ["seniority mismatch"], possible_duplicate: true, stale: true },
];

describe("JobsInbox", () => {
  it("filters simple job cards without offering a submission action", () => {
    render(<JobsInbox candidateId="example_candidate" jobs={jobs} />);
    expect(screen.getByText("ML Engineer")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /submit/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "All jobs" }));
    fireEvent.change(screen.getByRole("searchbox", { name: /search jobs/i }), {
      target: { value: "Senior" },
    });

    expect(screen.queryByText("ML Engineer")).not.toBeInTheDocument();
    expect(screen.getByText("Senior Analyst")).toBeInTheDocument();
    expect(screen.getByText(/possible duplicate/i)).toBeInTheDocument();
  });

  it("offers separate preparation and manual paths", () => {
    render(<JobsInbox candidateId="example_candidate" jobs={[jobs[0]]} />);

    expect(
      screen.getByRole("link", { name: /review ml engineer/i }),
    ).toHaveAttribute("href", "/jobs/job-1?candidate_id=example_candidate");

    const manual = screen.getByRole("link", {
      name: /apply manually for ml engineer/i,
    });
    expect(manual).toHaveAttribute("href", "https://jobs.example.invalid/1");
    expect(manual).toHaveAttribute("target", "_blank");
    expect(screen.getByText(/not recorded as submitted here/i)).toBeInTheDocument();
  });

  it("can hide jobs with unresolved blockers", () => {
    render(<JobsInbox candidateId="example_candidate" jobs={jobs} />);
    fireEvent.click(screen.getByRole("button", { name: "All jobs" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /ready to prepare/i }));
    expect(screen.getByText("ML Engineer")).toBeInTheDocument();
    expect(screen.queryByText("Senior Analyst")).not.toBeInTheDocument();
  });

  it("opens mobile filters, applies real score data, resets, and returns focus", () => {
    render(<JobsInbox candidateId="example_candidate" jobs={jobs} />);
    const trigger = screen.getByRole("button", { name: "Open job filters" });
    trigger.focus();
    fireEvent.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "Filters" });
    expect(dialog).toBeVisible();
    fireEvent.change(screen.getByRole("slider", { name: /minimum match score/i }), {
      target: { value: "90" },
    });
    expect(screen.getByText("No jobs match these filters")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByText("ML Engineer")).toBeVisible();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Filters" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
