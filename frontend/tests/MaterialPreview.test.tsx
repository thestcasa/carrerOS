import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MaterialPreview } from "@/components/MaterialPreview";
import type { ApplicationDetail, ApplicationDocumentView } from "@/lib/types";

function document(
  documentId: string,
  kind: "cv" | "cover_letter",
  version: number,
  content: string,
  immutable: boolean,
): ApplicationDocumentView {
  return {
    document_id: documentId,
    kind,
    version,
    content,
    sha256: documentId.repeat(64).slice(0, 64),
    immutable,
    validated: true,
    evidence_ids: ["experience_example_1"],
    created_at: `2026-08-0${version}T10:00:00Z`,
    provenance: [{
      text: "Built typed APIs",
      evidence_ids: ["experience_example_1"],
      source_paths: ["experience[0]"],
    }],
    revision_actor: version > 1 ? "local-user" : null,
    base_document_id: version > 1 ? "base-document" : null,
    render_metadata: {
      template_id: "technical_two_page",
      template_version: "1.0",
      page_count: 2,
      extraction_matches: true,
    },
  };
}

const application: ApplicationDetail = {
  application_id: "application-1",
  candidate_id: "example_candidate",
  job_id: "job-1",
  company: "Fictional Robotics Ltd",
  role: "ML Engineer",
  score: 91,
  state: "review_pending",
  last_event: "INDEPENDENT_REVIEW_COMPLETED",
  updated_at: "2026-08-05T10:00:00Z",
  next_action: "Review materials",
  source_url: "https://synthetic.invalid/job/1",
  ats_platform: "greenhouse",
  documents: [
    document("c", "cover_letter", 2, "Cover letter version two", false),
    document("v", "cv", 2, "CV version two", false),
    document("o", "cv", 1, "CV immutable version one", true),
  ],
  answers: [],
  events: [],
  review: { decision: "pass", semantic_passed: true, report: {} },
  correspondence: [],
  archive_available: false,
  confirmation_reference: null,
  submitted_at: null,
};

describe("MaterialPreview", () => {
  it("selects same-version documents by identity and kind", () => {
    render(<MaterialPreview application={application} onSaveRevision={vi.fn()} />);

    expect(screen.getByText("Cover letter version two")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /cv · version 2/i }));
    expect(screen.getByText("CV version two")).toBeInTheDocument();
    expect(screen.queryByText("Cover letter version two")).not.toBeInTheDocument();
    expect(screen.getByText("experience_example_1")).toBeInTheDocument();
    expect(screen.getByText("technical_two_page@1.0")).toBeInTheDocument();
  });

  it("saves an edited latest draft as a new version request", async () => {
    const onSaveRevision = vi.fn().mockResolvedValue({
      ...application,
      documents: [
        document("n", "cover_letter", 3, "Revised cover letter", false),
        { ...application.documents[0], immutable: true },
        ...application.documents.slice(1),
      ],
    });
    render(<MaterialPreview application={application} onSaveRevision={onSaveRevision} />);

    fireEvent.click(screen.getByRole("button", { name: "Edit selected draft" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Material content" }), {
      target: { value: "Revised cover letter" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Revision reason (optional)" }), {
      target: { value: "Focus on approved API work" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save as new version" }));

    await waitFor(() => expect(onSaveRevision).toHaveBeenCalledWith({
      document_id: "c",
      base_version: 2,
      content: "Revised cover letter",
      reason: "Focus on approved API work",
    }));
  });

  it("cancels without changing the immutable history", () => {
    const onSaveRevision = vi.fn();
    render(<MaterialPreview application={application} onSaveRevision={onSaveRevision} />);

    fireEvent.click(screen.getByRole("button", { name: "Edit selected draft" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Material content" }), {
      target: { value: "Unsaved content" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Cancel editing" }));
    expect(screen.getByText("Cover letter version two")).toBeInTheDocument();
    expect(onSaveRevision).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /cv · version 1/i }));
    expect(screen.getByText("Immutable history", { selector: ".material-state" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit selected draft" })).toBeDisabled();
  });
});
