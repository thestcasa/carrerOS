import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { JobDetail } from "@/components/JobDetail";
import type { JobDetail as JobDetailData } from "@/lib/types";

const job: JobDetailData = {
  job_id: "job-1", candidate_id: "example_candidate", company: "Fictional Labs", title: "ML Engineer", location: "Remote", remote_policy: "remote", source: "official", source_url: "https://jobs.example.invalid/1", ats_platform: "greenhouse", posted_at: null, verified_open_at: null, salary_display: null, role_category: "target", score: 87, state: "discovered", hard_blockers: [], possible_duplicate: false, stale: false,
  description_raw: "Build models", description_normalized: "Build models", source_verified: false, source_trust_level: "official", classification_confidence: 0.9, proposed_action: "prepare", required_skills: ["Python"], preferred_skills: [], requirements: [], score_dimensions: [], bonuses: [], penalties: [], salary_evidence: null, salary_confidence: null, selected_experience: [], selected_projects: [], security_findings: [],
};

describe("JobDetail actions", () => {
  it("exposes review actions but no submission control", () => {
    const onAction = vi.fn();
    render(<JobDetail job={job} onAction={onAction} />);
    fireEvent.click(screen.getByRole("button", { name: /shortlist/i }));
    expect(onAction).toHaveBeenCalledWith("shortlist");
    expect(screen.queryByRole("button", { name: /^submit/i })).not.toBeInTheDocument();
    expect(screen.getByText(/cannot authorize or submit/i)).toBeInTheDocument();
  });

  it("announces a failed action and disables controls while busy", () => {
    render(<JobDetail job={job} busyAction="verify" actionError="Source verification failed safely." onAction={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/failed safely/i);
    expect(screen.getByRole("button", { name: /verifying/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /shortlist/i })).toBeDisabled();
  });
});
