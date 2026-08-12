import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApplicationPipeline } from "@/components/ApplicationPipeline";
import type { ApplicationSummary } from "@/lib/types";

const application: ApplicationSummary = {
  application_id: "application-1",
  candidate_id: "example_candidate",
  job_id: "job-1",
  company: "Fictional Labs",
  role: "ML Engineer",
  score: 88,
  state: "human_action_required",
  last_event: "HUMAN_ACTION_REQUIRED",
  updated_at: new Date().toISOString(),
  next_action: "Complete the CAPTCHA yourself",
};

describe("ApplicationPipeline", () => {
  it("supports list and board views without adding a submission action", () => {
    render(<ApplicationPipeline candidateId="example_candidate" applications={[application]} />);

    expect(screen.getByLabelText("Application list")).toHaveTextContent("Age in state");
    expect(screen.queryByRole("button", { name: /submit/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Board" }));
    expect(screen.getByRole("region", { name: "Human action required" })).toHaveTextContent(
      "Complete the CAPTCHA yourself",
    );
    expect(screen.getByRole("region", { name: "Ready to submit" })).toHaveTextContent(
      "No applications",
    );
  });
});
