import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { JobsInbox } from "@/components/JobsInbox";
import type { JobSummary } from "@/lib/types";

const jobs: JobSummary[] = [
  { job_id: "job-1", candidate_id: "example_candidate", company: "Fictional Labs", title: "ML Engineer", location: "Remote", remote_policy: "remote", source: "official", source_url: "https://jobs.example.invalid/1", ats_platform: "greenhouse", posted_at: "2026-08-01", verified_open_at: "2026-08-04", salary_display: null, role_category: "target", score: 87, state: "shortlisted", hard_blockers: [], possible_duplicate: false, stale: false },
  { job_id: "job-2", candidate_id: "example_candidate", company: "Example Systems", title: "Senior Analyst", location: "Paris", remote_policy: "onsite", source: "official", source_url: "https://jobs.example.invalid/2", ats_platform: "lever", posted_at: null, verified_open_at: null, salary_display: null, role_category: "non_target", score: 40, state: "blocked", hard_blockers: ["seniority mismatch"], possible_duplicate: true, stale: true },
];

describe("JobsInbox", () => {
  it("filters jobs without offering a submission action", () => {
    render(<JobsInbox candidateId="example_candidate" jobs={jobs} />);
    expect(screen.getByText("ML Engineer")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /submit/i })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox", { name: /search jobs/i }), { target: { value: "Senior" } });
    expect(screen.queryByText("ML Engineer")).not.toBeInTheDocument();
    expect(screen.getByText("Senior Analyst")).toBeInTheDocument();
    expect(screen.getByText(/possible duplicate/i)).toBeInTheDocument();
  });

  it("creates a candidate-scoped analysis link", () => {
    render(<JobsInbox candidateId="example_candidate" jobs={[jobs[0]]} />);
    expect(screen.getByRole("link", { name: /review ml engineer/i })).toHaveAttribute("href", "/jobs/job-1?candidate_id=example_candidate");
  });
});
