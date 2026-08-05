import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApplicationPageClient } from "@/app/applications/[applicationId]/application-page-client";
import { api } from "@/lib/api";
import type { ApplicationDetail, ArtifactView } from "@/lib/types";

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

const renderedCv: ArtifactView = {
  artifact_id: "00000000-0000-0000-0000-000000000444",
  application_id: ready.application_id,
  candidate_id: ready.candidate_id,
  kind: "rendered_cv",
  version: 1,
  sha256: "a".repeat(64),
  content_type: "application/pdf",
  immutable: false,
  download_path: "/api/fixture",
  metadata: {
    template_id: "technical_two_page",
    template_version: "1.0",
    candidate_snapshot_version: "1.0.0",
    page_count: 2,
    extraction_matches: true,
    valid: true,
  },
  created_at: "2026-08-05T10:00:00Z",
};

describe("ApplicationPageClient", () => {
  beforeEach(() => {
    vi.mocked(api.artifacts).mockReset();
    vi.mocked(api.application).mockReset();
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

  it("shows the exact rendered draft and its structural validation metadata", async () => {
    vi.mocked(api.artifacts).mockReset();
    vi.mocked(api.artifacts).mockResolvedValueOnce([renderedCv]);
    vi.mocked(api.application).mockReset();
    vi.mocked(api.application).mockResolvedValueOnce({ ...ready, archive_available: false });

    render(
      <ApplicationPageClient
        candidateId="example_candidate"
        applicationId={ready.application_id}
      />,
    );

    expect(await screen.findByText("rendered_cv v1 · draft")).toBeVisible();
    expect(screen.getByText(/Template technical_two_page@1.0/)).toHaveTextContent(
      "snapshot 1.0.0 · 2 page(s) · extraction matched · validation passed",
    );
    expect(screen.getByRole("button", { name: "Download exact artifact" })).toBeEnabled();
  });
});
