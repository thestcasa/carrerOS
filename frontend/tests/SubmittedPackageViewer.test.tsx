import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SubmittedPackageViewer } from "@/components/SubmittedPackageViewer";
import { api } from "@/lib/api";
import type { ArtifactView } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  api: { downloadArtifact: vi.fn() },
}));

const applicationId = "00000000-0000-0000-0000-000000000111";
const candidateId = "example_candidate";

function artifact(
  kind: string,
  artifactId: string,
  contentType: string,
  options: Partial<ArtifactView> = {},
): ArtifactView {
  return {
    artifact_id: artifactId,
    application_id: applicationId,
    candidate_id: candidateId,
    kind,
    version: 1,
    sha256: kind.slice(0, 1).padEnd(64, "a"),
    content_type: contentType,
    immutable: true,
    download_path: `/api/artifacts/${artifactId}`,
    metadata: { submitted_exact: kind.startsWith("submitted_") },
    created_at: "2026-08-05T10:00:00Z",
    ...options,
  };
}

const submittedCv = artifact(
  "submitted_cv",
  "00000000-0000-0000-0000-000000000701",
  "application/pdf",
);
const submittedCoverLetter = artifact(
  "submitted_cover_letter",
  "00000000-0000-0000-0000-000000000702",
  "application/pdf",
);
const submittedAnswers = artifact(
  "submitted_answers",
  "00000000-0000-0000-0000-000000000703",
  "application/json",
);
const preSubmitReceipt = artifact(
  "submission_receipt",
  "00000000-0000-0000-0000-000000000704",
  "application/json",
);
const finalReceipt = artifact(
  "submission_receipt",
  "00000000-0000-0000-0000-000000000705",
  "application/json",
  { version: 2, created_at: "2026-08-05T11:00:00Z" },
);
const renderedDraft = artifact(
  "rendered_cv",
  "00000000-0000-0000-0000-000000000706",
  "application/pdf",
  { immutable: false },
);

const packageArtifacts = [
  renderedDraft,
  preSubmitReceipt,
  submittedCv,
  submittedCoverLetter,
  submittedAnswers,
  finalReceipt,
];

describe("SubmittedPackageViewer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.downloadArtifact).mockReset();
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:exact-submitted-artifact"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
  });

  it("shows four distinct immutable cards and excludes drafts", () => {
    render(
      <SubmittedPackageViewer
        applicationId={applicationId}
        artifacts={packageArtifacts}
        candidateId={candidateId}
        confirmationReference="synthetic-confirmation-111"
      />,
    );

    const cv = screen.getByRole("article", { name: "Exact submitted CV" });
    const cover = screen.getByRole("article", { name: "Exact submitted cover letter" });
    const answers = screen.getByRole("article", { name: "Exact submitted answers" });
    const receipt = screen.getByRole("article", { name: "Final submission receipt" });
    expect(cv).toHaveTextContent(submittedCv.artifact_id);
    expect(cover).toHaveTextContent(submittedCoverLetter.artifact_id);
    expect(answers).toHaveTextContent(submittedAnswers.artifact_id);
    expect(receipt).toHaveTextContent(finalReceipt.artifact_id);
    expect(receipt).toHaveTextContent("Version2");
    expect(receipt).toHaveTextContent("application/json");
    expect(receipt).toHaveTextContent("Immutable");
    expect(receipt).toHaveTextContent("synthetic-confirmation-111");
    expect(screen.queryByText(renderedDraft.artifact_id)).not.toBeInTheDocument();
    expect(screen.queryByText(preSubmitReceipt.artifact_id)).not.toBeInTheDocument();
  });

  it("downloads the exact PDF artifact by ID", async () => {
    const pdf = new Blob(["%PDF-1.4"], { type: "application/pdf" });
    vi.mocked(api.downloadArtifact).mockResolvedValue(pdf);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(
      <SubmittedPackageViewer
        applicationId={applicationId}
        artifacts={packageArtifacts}
        candidateId={candidateId}
        confirmationReference="synthetic-confirmation-111"
      />,
    );

    fireEvent.click(
      within(screen.getByRole("article", { name: "Exact submitted CV" })).getByRole(
        "button",
        { name: "Download exact PDF" },
      ),
    );

    await waitFor(() =>
      expect(api.downloadArtifact).toHaveBeenCalledWith(
        candidateId,
        applicationId,
        submittedCv.artifact_id,
      ),
    );
    expect(URL.createObjectURL).toHaveBeenCalledWith(pdf);
    expect(click).toHaveBeenCalledOnce();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:exact-submitted-artifact");
    click.mockRestore();
  });

  it("renders answers and the final receipt as escaped inert text using exact IDs", async () => {
    const answersText = '{"answer":"<script>globalThis.compromised=true</script>"}';
    vi.mocked(api.downloadArtifact).mockImplementation(async (_candidate, _application, id) => {
      const text = id === submittedAnswers.artifact_id
        ? answersText
        : '{"status":"confirmed"}';
      return { text: vi.fn().mockResolvedValue(text) } as unknown as Blob;
    });
    const view = render(
      <SubmittedPackageViewer
        applicationId={applicationId}
        artifacts={packageArtifacts}
        candidateId={candidateId}
        confirmationReference="synthetic-confirmation-111"
      />,
    );

    fireEvent.click(
      within(screen.getByRole("article", { name: "Exact submitted answers" })).getByRole(
        "button",
        { name: "Preview escaped text" },
      ),
    );
    expect(
      await screen.findByLabelText("Exact submitted answers escaped text preview"),
    ).toHaveTextContent(answersText);
    expect(view.container.querySelector("script")).toBeNull();

    fireEvent.click(
      within(screen.getByRole("article", { name: "Final submission receipt" })).getByRole(
        "button",
        { name: "Preview escaped text" },
      ),
    );
    await screen.findByText('{"status":"confirmed"}');
    expect(vi.mocked(api.downloadArtifact).mock.calls).toEqual([
      [candidateId, applicationId, submittedAnswers.artifact_id],
      [candidateId, applicationId, finalReceipt.artifact_id],
    ]);
  });

  it("fails closed until the backend records confirmation", () => {
    render(
      <SubmittedPackageViewer
        applicationId={applicationId}
        artifacts={packageArtifacts}
        candidateId={candidateId}
        confirmationReference={null}
      />,
    );

    expect(screen.getByText(/No backend confirmation is recorded/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /exact PDF|escaped text/ })).not.toBeInTheDocument();
    expect(api.downloadArtifact).not.toHaveBeenCalled();
  });

  it("does not present a pre-submit receipt as the final receipt", () => {
    render(
      <SubmittedPackageViewer
        applicationId={applicationId}
        artifacts={[preSubmitReceipt]}
        candidateId={candidateId}
        confirmationReference="synthetic-confirmation-111"
      />,
    );

    const receipt = screen.getByRole("article", { name: "Final submission receipt" });
    expect(receipt).toHaveTextContent("No immutable submitted artifact is recorded.");
    expect(receipt).not.toHaveTextContent(preSubmitReceipt.artifact_id);
  });
});
