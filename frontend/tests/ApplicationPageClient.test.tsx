import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApplicationPageClient } from "@/app/applications/[applicationId]/application-page-client";
import { api } from "@/lib/api";
import type { ApplicationDetail } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  api: {
    application: vi.fn(),
    artifacts: vi.fn(),
    authorize: vi.fn(),
    submitSynthetic: vi.fn(),
    dryRun: vi.fn(),
    applicationCommand: vi.fn(),
    downloadArtifact: vi.fn(),
  },
}));

const ready: ApplicationDetail = {
  application_id: "00000000-0000-0000-0000-000000000111",
  candidate_id: "example_candidate",
  job_id: "00000000-0000-0000-0000-000000000222",
  company: "Fictional Robotics Ltd",
  role: "Machine Learning Engineer",
  score: 88,
  state: "ready_to_submit",
  last_event: "FINAL_VALIDATION_PASSED",
  updated_at: "2026-08-05T10:00:00Z",
  next_action: "Authorize synthetic submission",
  source_url: "https://synthetic.invalid/job/1",
  ats_platform: "greenhouse",
  documents: [],
  answers: [],
  events: [],
  review: null,
  correspondence: [],
  archive_available: true,
  confirmation_reference: null,
  submitted_at: null,
};

describe("ApplicationPageClient", () => {
  beforeEach(() => {
    vi.mocked(api.artifacts).mockResolvedValue([]);
    vi.mocked(api.application)
      .mockResolvedValueOnce(ready)
      .mockResolvedValueOnce({
        ...ready,
        state: "failed_retryable",
        next_action: "Inspect and retry",
        last_event: "SUBMISSION_CONFIRMATION_MISSING",
      });
    vi.mocked(api.authorize).mockResolvedValue({
      authorization_id: "00000000-0000-0000-0000-000000000333",
      application_id: ready.application_id,
      candidate_id: ready.candidate_id,
      workflow_state: "ready_to_submit",
      issued_at: "2026-08-05T10:00:00Z",
      expires_at: "2026-08-05T10:05:00Z",
    });
    vi.mocked(api.submitSynthetic).mockResolvedValue({
      application_id: ready.application_id,
      state: "failed_retryable",
      successful: false,
      status: "confirmation_missing",
      confirmation_reference: null,
    });
  });

  it("does not claim success when backend confirmation is missing", async () => {
    render(
      <ApplicationPageClient
        candidateId="example_candidate"
        applicationId={ready.application_id}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "authorize submit" }));

    await waitFor(() => expect(screen.getByText("Inspect and retry")).toBeInTheDocument());
    expect(screen.getByText("No backend confirmation yet")).toBeInTheDocument();
    expect(screen.queryByText(/^confirmed$/i)).not.toBeInTheDocument();
  });
});
