import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "@/components/AppShell";
import { ProfilePageClient } from "@/app/candidates/[candidateId]/profile/profile-page-client";
import { ReadinessPageClient } from "@/app/candidates/[candidateId]/readiness/readiness-page-client";

vi.mock("@/lib/api", () => ({
  api: {
    candidate: vi.fn(),
    readiness: vi.fn(),
    humanActions: vi.fn(),
  },
}));

import { api } from "@/lib/api";

const readiness = {
  candidate_id: "route_candidate",
  status: "ready" as const,
  issues: [],
  domains: [],
  capabilities: [],
};

describe("candidate route selection", () => {
  beforeEach(() => {
    vi.mocked(api.candidate).mockImplementation(async (candidateId) => ({
      candidate_id: candidateId,
      profile_version: "1.0.0",
      config: { identity: {} },
      readiness: { ...readiness, candidate_id: candidateId },
    }));
    vi.mocked(api.humanActions).mockResolvedValue([]);
    vi.mocked(api.readiness).mockImplementation(async (candidateId) => ({
      ...readiness,
      candidate_id: candidateId,
    }));
  });

  it.each([
    ["profile", <ProfilePageClient key="profile" candidateId="profile_candidate" />],
    ["readiness", <ReadinessPageClient key="readiness" candidateId="readiness_candidate" />],
  ])("synchronizes the active candidate from a direct %s route", async (_name, page) => {
    document.cookie = "careeros_active_candidate=example_candidate; Path=/";
    render(<AppShell>{page}</AppShell>);

    const expected = _name === "profile" ? "profile_candidate" : "readiness_candidate";
    await waitFor(() => expect(screen.getByText(`Active: ${expected}`)).toBeVisible());
    expect(document.cookie).toContain(`careeros_active_candidate=${expected}`);
  });

  it("does not persist a candidate that the backend cannot resolve", async () => {
    vi.mocked(api.candidate).mockRejectedValueOnce(new Error("Candidate not found"));
    document.cookie = "careeros_active_candidate=example_candidate; Path=/";

    render(<AppShell><ProfilePageClient candidateId="missing_candidate" /></AppShell>);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Candidate not found"));
    expect(document.cookie).toContain("careeros_active_candidate=example_candidate");
    expect(document.cookie).not.toContain("careeros_active_candidate=missing_candidate");
  });
});
