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
    reviseMaterial: vi.fn(),
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

const editable: ApplicationDetail = {
  ...ready,
  state: "review_pending",
  next_action: "Review materials",
  archive_available: false,
  review: { decision: "pass", semantic_passed: true, report: {} },
  documents: [{
    document_id: "00000000-0000-0000-0000-000000000555",
    kind: "cv",
    version: 1,
    content: "Original approved CV content",
    sha256: "b".repeat(64),
    immutable: false,
    validated: true,
    evidence_ids: ["experience_example_1"],
    created_at: "2026-08-05T10:00:00Z",
    provenance: [{ text: "Built typed APIs", evidence_ids: ["experience_example_1"] }],
    revision_actor: null,
    base_document_id: null,
    render_metadata: {
      template_id: "technical_two_page",
      template_version: "1.0",
      page_count: 2,
      extraction_matches: true,
    },
  }],
};

describe("ApplicationPageClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.artifacts).mockReset();
    vi.mocked(api.application).mockReset();
    vi.mocked(api.reviseMaterial).mockReset();
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

  it("reuses authorization and submission keys after an uncertain failure", async () => {
    vi.mocked(api.submitSynthetic)
      .mockRejectedValueOnce(new Error("connection interrupted"))
      .mockResolvedValueOnce({
        application_id: ready.application_id,
        state: "failed_retryable",
        successful: false,
        status: "confirmation_missing",
        confirmation_reference: null,
      });
    render(
      <ApplicationPageClient
        candidateId="example_candidate"
        applicationId={ready.application_id}
      />,
    );
    const button = await screen.findByRole("button", { name: "authorize submit" });

    fireEvent.click(button);
    await screen.findByRole("alert");
    fireEvent.click(button);
    await waitFor(() => expect(api.submitSynthetic).toHaveBeenCalledTimes(2));

    expect(vi.mocked(api.authorize).mock.calls[1][2]).toBe(
      vi.mocked(api.authorize).mock.calls[0][2],
    );
    expect(vi.mocked(api.submitSynthetic).mock.calls[1][3]).toBe(
      vi.mocked(api.submitSynthetic).mock.calls[0][3],
    );
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

  it("sends the exact revision and reuses its idempotency key after an uncertain failure", async () => {
    const revisionResult: ApplicationDetail = {
      ...editable,
      documents: [
        {
          ...editable.documents[0],
          document_id: "00000000-0000-0000-0000-000000000666",
          version: 2,
          content: "Revised approved CV content",
          sha256: "c".repeat(64),
          revision_actor: "local-user",
          base_document_id: editable.documents[0].document_id,
        },
        { ...editable.documents[0], immutable: true },
      ],
    };
    vi.mocked(api.application).mockReset();
    vi.mocked(api.application).mockResolvedValue(editable);
    vi.mocked(api.reviseMaterial)
      .mockRejectedValueOnce(new Error("connection interrupted"))
      .mockResolvedValueOnce(revisionResult);

    render(
      <ApplicationPageClient
        candidateId="example_candidate"
        applicationId={ready.application_id}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Edit selected draft" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Material content" }), {
      target: { value: "Revised approved CV content" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Revision reason (optional)" }), {
      target: { value: "Clarify approved experience" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save as new version" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("connection interrupted");
    fireEvent.click(screen.getByRole("button", { name: "Save as new version" }));

    await waitFor(() => expect(api.reviseMaterial).toHaveBeenCalledTimes(2));
    const expectedRevision = {
      document_id: editable.documents[0].document_id,
      base_version: 1,
      content: "Revised approved CV content",
      reason: "Clarify approved experience",
    };
    expect(vi.mocked(api.reviseMaterial).mock.calls[0].slice(0, 3)).toEqual([
      "example_candidate",
      ready.application_id,
      expectedRevision,
    ]);
    expect(vi.mocked(api.reviseMaterial).mock.calls[1].slice(0, 3)).toEqual([
      "example_candidate",
      ready.application_id,
      expectedRevision,
    ]);
    expect(vi.mocked(api.reviseMaterial).mock.calls[1][3]).toBe(
      vi.mocked(api.reviseMaterial).mock.calls[0][3],
    );
  });
});
