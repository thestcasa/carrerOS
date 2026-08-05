import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ActionsPageClient } from "@/app/actions/actions-page-client";
import { api } from "@/lib/api";
import type { HumanActionView } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  api: {
    humanActions: vi.fn(),
    openHumanSession: vi.fn(),
    completeHumanAction: vi.fn(),
  },
}));

const pending: HumanActionView = {
  action_id: "00000000-0000-0000-0000-000000000001",
  candidate_id: "example_candidate",
  application_id: "00000000-0000-0000-0000-000000000002",
  company: "Fictional Robotics Ltd",
  role: "Machine Learning Engineer",
  kind: "captcha",
  status: "pending",
  reason: "CAPTCHA requires human completion in this session.",
  created_at: "2026-08-05T10:00:00Z",
  expires_at: "2026-08-05T10:15:00Z",
  screenshot_available: true,
  browser_session_id: "00000000-0000-0000-0000-000000000003",
  session_opened: false,
};

describe("ActionsPageClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.humanActions).mockResolvedValue([pending]);
    vi.mocked(api.openHumanSession).mockResolvedValue({ ...pending, session_opened: true });
  });

  it("opens the recoverable session before allowing completion", async () => {
    render(<ActionsPageClient candidateId="example_candidate" />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Open recoverable browser session" }),
    );

    await waitFor(() => expect(api.openHumanSession).toHaveBeenCalledOnce());
    expect(api.completeHumanAction).not.toHaveBeenCalled();
  });

  it("reuses the open-session key after an uncertain failure", async () => {
    vi.mocked(api.openHumanSession)
      .mockRejectedValueOnce(new Error("connection interrupted"))
      .mockResolvedValueOnce({ ...pending, session_opened: true });
    render(<ActionsPageClient candidateId="example_candidate" />);
    const button = await screen.findByRole("button", {
      name: "Open recoverable browser session",
    });

    fireEvent.click(button);
    await screen.findByRole("alert");
    fireEvent.click(button);
    await waitFor(() => expect(api.openHumanSession).toHaveBeenCalledTimes(2));

    expect(vi.mocked(api.openHumanSession).mock.calls[1][2]).toBe(
      vi.mocked(api.openHumanSession).mock.calls[0][2],
    );
  });
});
