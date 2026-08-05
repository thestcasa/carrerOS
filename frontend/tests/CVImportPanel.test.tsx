import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CVImportPanel } from "@/components/CVImportPanel";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    createCvImport: vi.fn(),
    applyCvImport: vi.fn(),
  },
}));

describe("CVImportPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.createCvImport).mockResolvedValue({
      import_id: "cv_aaaaaaaaaaaaaaaaaaaa",
      candidate_id: "example_candidate",
      source_filename: "fictional.txt",
      source_sha256: "a".repeat(64),
      education: { items: [{}] },
      experience: { items: [{}] },
      warnings: ["Review every field."],
      approval_required: true,
      applied_profile_version: null,
    });
  });

  it("previews extraction before explicitly applying unapproved facts", async () => {
    const onApplied = vi.fn();
    render(<CVImportPanel candidateId="example_candidate" onApplied={onApplied} />);
    const file = new File(["EDUCATION"], "fictional.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("CV file"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Extract unapproved draft" }));

    expect(await screen.findByText(/Detected 1 education and 1 experience/)).toBeVisible();
    expect(api.applyCvImport).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Apply as unapproved facts" }));
    await waitFor(() => expect(api.applyCvImport).toHaveBeenCalledOnce());
  });
});
