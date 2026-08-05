import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MaterialPreview } from "@/components/MaterialPreview";
import type { ApplicationMaterials } from "@/lib/types";

const materials: ApplicationMaterials = {
  candidate_id: "example_candidate",
  application_id: "application-1",
  company: "Fictional Robotics Ltd",
  role: "ML Engineer",
  versions: [
    { version: 2, kind: "cover_letter", lifecycle: "draft", created_at: "2026-08-04", content_sha256: "a".repeat(64), content: "Draft for Fictional Robotics Ltd", claims: [{ text: "Built typed APIs", evidence_ids: ["experience_example_1"] }], validation: { valid: true, issues: [] }, review: { decision: "pass", documents_supported: true, answers_supported: true, issues: [] } },
    { version: 1, kind: "cover_letter", lifecycle: "immutable", created_at: "2026-08-03", content_sha256: "b".repeat(64), content: "Snapshot for Fictional Robotics Ltd", claims: [{ text: "Built typed APIs", evidence_ids: ["experience_example_1"] }], validation: { valid: true, issues: [] }, review: { decision: "pass", documents_supported: true, answers_supported: true, issues: [] } },
  ],
};

describe("MaterialPreview", () => {
  it("shows provenance, review results, and safe draft-only actions", () => {
    const onAction = vi.fn();
    render(<MaterialPreview materials={materials} onAction={onAction} />);

    expect(screen.getByText("Editable draft", { selector: ".material-state" })).toBeInTheDocument();
    expect(screen.getByText("experience_example_1")).toBeInTheDocument();
    expect(screen.getByText(/all deterministic checks passed/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^submit/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve material" }));
    expect(onAction).toHaveBeenCalledWith("approve", expect.objectContaining({ version: 2 }));
  });

  it("renders immutable history read-only", () => {
    render(<MaterialPreview materials={materials} />);
    fireEvent.click(screen.getByRole("button", { name: /version 1/i }));

    expect(screen.getByText("Immutable snapshot", { selector: ".material-state" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit draft" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Regenerate" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Approve material" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject material" })).toBeDisabled();
  });

  it("blocks approval when deterministic review fails", () => {
    const blocked: ApplicationMaterials = { ...materials, versions: [{ ...materials.versions[0], validation: { valid: false, issues: [{ code: "wrong_company", severity: "error", message: "Wrong company detected." }] }, review: { decision: "fail", documents_supported: false, answers_supported: true, issues: [] } }] };
    render(<MaterialPreview materials={blocked} />);

    expect(screen.getByText("Wrong company detected.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve material" })).toBeDisabled();
  });
});
