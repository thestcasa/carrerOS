import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProfileEditor } from "@/components/ProfileEditor";
import { api } from "@/lib/api";
import type { CandidateDetail } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  api: { updateSection: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

const detail = {
  candidate_id: "example_candidate",
  profile_version: "1.0.0",
  config: {
    certifications: {
      items: [
        {
          id: "fictional_certificate",
          name: "Fictional Certificate",
          issuer: "Example Institute",
          approved: true,
          archived: false,
        },
      ],
    },
  },
  readiness: { candidate_id: "example_candidate", status: "ready", issues: [], domains: [], capabilities: [] },
} as CandidateDetail;

describe("ProfileEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.updateSection).mockResolvedValue({
      candidate_id: "example_candidate",
      previous_version: "1.0.0",
      profile_version: "1.0.1",
      section: "certifications",
      readiness: detail.readiness,
    });
  });

  it("saves the latest structured facts without flattening stable IDs", async () => {
    render(<ProfileEditor detail={detail} initialSection="certifications" />);
    const textarea = screen.getByRole("textbox", { name: /^Items/ });
    const updated = [
      {
        id: "fictional_certificate",
        name: "Updated Fictional Certificate",
        issuer: "Example Institute",
        approved: false,
        archived: false,
      },
    ];

    fireEvent.change(textarea, { target: { value: JSON.stringify(updated, null, 2) } });
    fireEvent.click(screen.getByRole("button", { name: "Save new version" }));

    await waitFor(() =>
      expect(api.updateSection).toHaveBeenCalledWith(
        "example_candidate",
        "certifications",
        { items: updated },
        expect.stringMatching(/^update-profile-/),
      ),
    );
  });

  it("reuses the command key when an uncertain save is retried", async () => {
    vi.mocked(api.updateSection)
      .mockRejectedValueOnce(new Error("connection interrupted"))
      .mockResolvedValueOnce({
        candidate_id: "example_candidate",
        previous_version: "1.0.0",
        profile_version: "1.0.1",
        section: "certifications",
        readiness: detail.readiness,
      });
    render(<ProfileEditor detail={detail} initialSection="certifications" />);
    const textarea = screen.getByRole("textbox", { name: /^Items/ });
    const updated = [
      {
        id: "fictional_certificate",
        name: "Fictional Certificate",
        issuer: "Example Institute",
        approved: false,
        archived: false,
      },
    ];
    fireEvent.change(textarea, { target: { value: JSON.stringify(updated, null, 2) } });

    fireEvent.click(screen.getByRole("button", { name: "Save new version" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Save new version" }));
    await waitFor(() => expect(api.updateSection).toHaveBeenCalledTimes(2));

    expect(vi.mocked(api.updateSection).mock.calls[1][3]).toBe(
      vi.mocked(api.updateSection).mock.calls[0][3],
    );
  });

  it("disables saving while structured JSON is invalid", () => {
    render(<ProfileEditor detail={detail} initialSection="certifications" />);
    fireEvent.change(screen.getByRole("textbox", { name: /^Items/ }), {
      target: { value: "[{not-json}]" },
    });

    expect(screen.getByRole("button", { name: "Save new version" })).toBeDisabled();
    expect(api.updateSection).not.toHaveBeenCalled();
  });
});
