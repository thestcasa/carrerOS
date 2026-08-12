import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { JobDetail } from "@/components/JobDetail";
import type { JobDetail as JobDetailData } from "@/lib/types";

const job: JobDetailData = {
  job_id: "job-1", candidate_id: "example_candidate", external_job_id: "gh-101", requisition_id: "REQ-101", company: "Fictional Labs", company_domain: "fictional.invalid", company_stage: "scaleup", team: "Applied AI", title: "ML Engineer", normalized_title: "machine learning engineer", location: "Remote, Spain", normalized_location: "spain", remote_policy: "remote", employment_type: "full_time", seniority: "early_career", source: "official", source_url: "https://jobs.example.invalid/1", ats_platform: "greenhouse", posted_at: "2026-08-01T10:00:00Z", deadline: "2026-09-01T23:59:59Z", expected_start_date: "2027-01-15", verified_open_at: null, salary_display: null, salary_min: "42000", salary_max: "50000", salary_currency: "EUR", salary_period: "gross_annual", salary_source: "job_post", visa_requirements: "No sponsorship available", work_authorization_requirements: "Authorized to work in Spain", required_experience_years_min: 1, required_experience_years_max: 3, required_languages: [{ language: "English", minimum_level: "B2" }], role_category: "target", score: 87, state: "discovered", hard_blockers: [], possible_duplicate: false, stale: false,
  description_raw: "Build models", description_normalized: "Build models", source_verified: false, source_trust_level: "official", classification_confidence: 0.9, proposed_action: "prepare", required_skills: ["Python"], preferred_skills: [], requirements: [], score_dimensions: [], bonuses: [], penalties: [], salary_evidence: null, salary_confidence: null, selected_experience: [], selected_projects: [], security_findings: [],
};

describe("JobDetail actions", () => {
  it("offers preparation and manual application without a submission control", () => {
    const onAction = vi.fn();
    render(<JobDetail job={job} onAction={onAction} />);

    fireEvent.click(screen.getByRole("button", { name: /prepare application/i }));
    expect(onAction).toHaveBeenCalledWith("generate");

    const manual = screen.getByRole("link", { name: /apply manually on official site/i });
    expect(manual).toHaveAttribute("href", job.source_url);
    expect(manual).toHaveAttribute("target", "_blank");
    expect(screen.getByText(/does not record an application or submission/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^submit/i })).not.toBeInTheDocument();
  });

  it("keeps save controls safe and disables actions while busy", () => {
    const onAction = vi.fn();
    render(
      <JobDetail
        job={job}
        busyAction="verify"
        actionError="Source verification failed safely."
        onAction={onAction}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(/failed safely/i);
    expect(screen.getByRole("button", { name: /prepare application/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /save job/i })).toBeDisabled();

    fireEvent.click(screen.getByText("Advanced job analysis"));
    expect(screen.getByRole("button", { name: /verifying/i })).toBeDisabled();
  });

  it("presents key eligibility first and technical source data on demand", () => {
    render(<JobDetail job={job} />);

    const eligibility = screen.getByRole("region", {
      name: "Employment and eligibility requirements",
    });
    expect(eligibility).toHaveTextContent("1–3 years");
    expect(eligibility).toHaveTextContent("English (B2 minimum)");
    expect(eligibility).toHaveTextContent("Authorized to work in Spain");
    expect(screen.getByRole("heading", { name: "EUR 42000–50000 gross_annual" })).toBeVisible();

    fireEvent.click(screen.getByText("Advanced job analysis"));
    const metadata = screen.getByRole("region", { name: "Normalized job metadata" });
    expect(metadata).toHaveTextContent("gh-101");
    expect(metadata).toHaveTextContent("machine learning engineer");
    expect(metadata).toHaveTextContent("Applied AI");
    expect(metadata).toHaveTextContent("2027-01-15");
  });

  it("blocks preparation when hard blockers remain but preserves the manual path", () => {
    render(<JobDetail job={{ ...job, hard_blockers: ["seniority mismatch"] }} />);
    expect(screen.getByRole("button", { name: /prepare application/i })).toBeDisabled();
    expect(screen.getByRole("link", { name: /apply manually/i })).toHaveAttribute(
      "href",
      job.source_url,
    );
  });
});
