import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReadinessBoard } from "@/components/ReadinessBoard";
import type { ReadinessReport } from "@/lib/types";

const report: ReadinessReport = {
  candidate_id: "example_candidate",
  status: "not_ready",
  issues: [
    {
      code: "legal_status_not_approved",
      message: "Legal status is not approved for automated use.",
      domain: "legal",
      field_path: "legal_status.approved_for_automated_use",
      severity: "blocking",
    },
  ],
  domains: [
    {
      domain: "legal",
      label: "Legal and work authorization",
      status: "BLOCKED",
      field_path: "legal_status",
      issues: [
        {
          code: "legal_status_not_approved",
          message: "Legal status is not approved for automated use.",
          domain: "legal",
          field_path: "legal_status.approved_for_automated_use",
          severity: "blocking",
        },
      ],
    },
  ],
  capabilities: [
    {
      capability: "controlled_submission",
      label: "Controlled submission",
      status: "BLOCKED",
      blockers: ["legal"],
    },
  ],
};

describe("ReadinessBoard", () => {
  it("shows capability blockers and links editable domains to the profile field", () => {
    render(<ReadinessBoard candidateId="example_candidate" report={report} />);
    expect(screen.getByText("Controlled submission")).toBeInTheDocument();
    expect(screen.getAllByText("Blocked")).toHaveLength(2);
    expect(screen.getByText("Legal status is not approved for automated use.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /edit domain/i })).toHaveAttribute(
      "href",
      "/candidates/example_candidate/profile?section=legal_status",
    );
  });

  it("links manifest approvals directly to the readiness controls", () => {
    const manifestReport: ReadinessReport = {
      ...report,
      domains: [
        {
          domain: "profile",
          label: "Profile approval",
          status: "BLOCKED",
          field_path: "manifest",
          issues: [
            {
              code: "profile_not_approved",
              message: "Candidate profile requires explicit approval.",
              domain: "profile",
              field_path: "manifest.validation.profile_approved",
              severity: "blocking",
            },
          ],
        },
      ],
    };
    render(<ReadinessBoard candidateId="example_candidate" report={manifestReport} />);

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(2);
    for (const link of links) {
      expect(link).toHaveAttribute(
        "href",
        "/candidates/example_candidate/profile?section=candidate_controls",
      );
    }
  });
});
