import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProfileEditor } from "@/components/ProfileEditor";
import { api } from "@/lib/api";
import type { CandidateDetail } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  api: { updateSection: vi.fn(), updateCandidateControls: vi.fn() },
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
    vi.mocked(api.updateCandidateControls).mockResolvedValue({
      candidate_id: "example_candidate",
      previous_version: "1.0.0",
      profile_version: "1.0.1",
      workflow: {
        discovery_enabled: true,
        automatic_submission_enabled: true,
        email_tracking_enabled: false,
        notifications_enabled: true,
      },
      validation: {
        profile_approved: true,
        legal_status_approved: true,
        automatic_answers_approved: true,
        cv_templates_approved: true,
      },
      readiness: detail.readiness,
    });
  });

  it("edits structured facts without exposing raw JSON or flattening stable IDs", async () => {
    render(<ProfileEditor detail={detail} initialSection="certifications" />);
    const updated = [
      {
        id: "fictional_certificate",
        name: "Updated Fictional Certificate",
        issuer: "Example Institute",
        approved: false,
        archived: false,
      },
    ];

    expect(screen.queryByText(/structured entries use JSON/i)).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Updated Fictional Certificate" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /Approved/ }));
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
    fireEvent.click(screen.getByRole("checkbox", { name: /Approved/ }));

    fireEvent.click(screen.getByRole("button", { name: "Save new version" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Save new version" }));
    await waitFor(() => expect(api.updateSection).toHaveBeenCalledTimes(2));

    expect(vi.mocked(api.updateSection).mock.calls[1][3]).toBe(
      vi.mocked(api.updateSection).mock.calls[0][3],
    );
  });

  it("adds, archives, and reorders structured entries with stable generated IDs", () => {
    render(<ProfileEditor detail={detail} initialSection="certifications" />);
    fireEvent.click(screen.getByRole("button", { name: "Add item" }));

    expect(screen.getAllByRole("article", { name: /^Items:/ })).toHaveLength(2);
    expect(screen.getByRole("button", { name: /Move Fictional Certificate down/ })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: /Move Fictional Certificate down/ }));
    fireEvent.click(screen.getAllByRole("button", { name: "Archive entry" })[0]);

    expect(screen.getByRole("button", { name: "Save new version" })).toBeEnabled();
  });

  it("can add the first item to an empty structured section", () => {
    const empty = {
      ...detail,
      config: { publications: { items: [] } },
    } as CandidateDetail;
    render(<ProfileEditor detail={empty} initialSection="publications" />);

    fireEvent.click(screen.getByRole("button", { name: "Add item" }));

    expect(screen.getByRole("textbox", { name: "Title" })).toBeVisible();
    expect((screen.getByRole("textbox", { name: "Id" }) as HTMLInputElement).value).toMatch(/^new_/);
  });

  it("requires an explicit candidate action to enable submission workflows", async () => {
    const controlsDetail = {
      ...detail,
      config: {
        manifest: {
          workflow: {
            discovery_enabled: true,
            automatic_submission_enabled: false,
            email_tracking_enabled: false,
            notifications_enabled: true,
          },
          validation: {
            profile_approved: false,
            legal_status_approved: false,
            automatic_answers_approved: false,
            cv_templates_approved: false,
          },
        },
      },
    } as CandidateDetail;
    render(<ProfileEditor detail={controlsDetail} initialSection="candidate_controls" />);

    fireEvent.click(screen.getByRole("checkbox", { name: /Profile approved/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Automatic submission enabled/ }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: /Acknowledge automatic submission consequences/ }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save new version" }));

    await waitFor(() =>
      expect(api.updateCandidateControls).toHaveBeenCalledWith(
        "example_candidate",
        expect.objectContaining({
          workflow: expect.objectContaining({ automatic_submission_enabled: true }),
          validation: expect.objectContaining({ profile_approved: true }),
          acknowledge_automatic_submission_consequences: true,
        }),
        expect.stringMatching(/^update-profile-/),
      ),
    );
    expect(api.updateSection).not.toHaveBeenCalled();
    expect(
      screen.getByText(/does not enable autonomous mode, confirm autonomy, or bypass manual approval/),
    ).toBeVisible();
  });
});
