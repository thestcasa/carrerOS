import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SettingsPageClient } from "@/app/settings/settings-page-client";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    settings: vi.fn(),
    updateSettings: vi.fn(),
    confirmAutonomy: vi.fn(),
    emergencyStop: vi.fn(),
    candidate: vi.fn(),
    discoverySources: vi.fn(),
    humanActions: vi.fn(),
    deletionStatus: vi.fn(),
    exportCandidate: vi.fn(),
    exportCandidateConfiguration: vi.fn(),
    importCandidateConfiguration: vi.fn(),
    deleteCandidate: vi.fn(),
  },
}));

describe("SettingsPageClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.deletionStatus).mockRejectedValue({
      code: "deletion_not_found",
    });
    vi.mocked(api.candidate).mockResolvedValue({
      candidate_id: "example_candidate",
      profile_version: "profile-v1",
      config: {},
      readiness: {
        candidate_id: "example_candidate",
        status: "ready",
        issues: [],
        domains: [],
        capabilities: [],
      },
    });
    vi.mocked(api.discoverySources).mockResolvedValue([]);
    vi.mocked(api.humanActions).mockResolvedValue([]);
    vi.mocked(api.settings).mockResolvedValue({
      candidate_id: "example_candidate",
      automation_mode: "approval_required",
      discovery_enabled: true,
      emergency_stopped: false,
      allowed_ats_adapters: ["greenhouse"],
      tested_ats_adapters: [],
      dry_run_acceptance_passed: false,
      explicit_autonomy_confirmation: false,
      maximum_applications_per_day: 3,
      maximum_applications_per_week: 10,
      maximum_applications_per_company_30_days: 1,
      browser_session_retention_days: 30,
      autonomy_blockers: [
        "no_tested_ats_adapter",
        "dry_run_acceptance_not_passed",
      ],
      autonomy_prerequisites: [],
    });
  });

  it("cannot enable autonomous mode while backend blockers exist", async () => {
    render(<SettingsPageClient candidateId="example_candidate" />);

    expect(
      await screen.findByRole("button", { name: "autonomous" }),
    ).toBeDisabled();
    expect(
      screen.getByText("Run a passing safe adapter check for an allowed ATS."),
    ).toBeInTheDocument();
    expect(api.updateSettings).not.toHaveBeenCalled();
  });

  it("records autonomy only after an unchecked consequence-aware confirmation", async () => {
    const scoped = {
      ...(await api.settings("example_candidate")),
      tested_ats_adapters: ["greenhouse" as const],
      dry_run_acceptance_passed: true,
      autonomy_blockers: ["explicit_confirmation_missing"],
      autonomy_prerequisites: [{
        code: "explicit_confirmation_missing",
        title: "Explicit controlled-autonomy confirmation",
        passed: false,
        explanation: "No confirmation exists for this exact tested scope.",
        resolution: "Read the consequences and confirm the exact scope yourself.",
        action_href: "#autonomy-confirmation",
        evidence_id: null,
        evidence_summary: null,
        evidenced_at: null,
      }],
    };
    vi.mocked(api.settings).mockResolvedValue(scoped);
    vi.mocked(api.confirmAutonomy).mockResolvedValue({
      ...scoped,
      explicit_autonomy_confirmation: true,
      autonomy_blockers: [],
      autonomy_prerequisites: scoped.autonomy_prerequisites.map((item) => ({
        ...item,
        passed: true,
        evidence_summary: "Audited confirmation for the current scope",
      })),
    });
    render(<SettingsPageClient candidateId="example_candidate" />);

    const record = await screen.findByRole("button", { name: "Record my confirmation" });
    expect(record).toBeDisabled();
    expect(api.confirmAutonomy).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("checkbox", { name: /understand these consequences/i }));
    fireEvent.click(record);

    await waitFor(() => expect(api.confirmAutonomy).toHaveBeenCalledWith(
      "example_candidate",
      expect.stringMatching(/^autonomy-confirmation-/),
    ));
  });

  it("persists discovery policy through the backend contract", async () => {
    vi.mocked(api.updateSettings).mockResolvedValue({
      candidate_id: "example_candidate",
      automation_mode: "approval_required",
      discovery_enabled: false,
      emergency_stopped: false,
      allowed_ats_adapters: ["greenhouse"],
      tested_ats_adapters: [],
      dry_run_acceptance_passed: false,
      explicit_autonomy_confirmation: false,
      maximum_applications_per_day: 3,
      maximum_applications_per_week: 10,
      maximum_applications_per_company_30_days: 1,
      browser_session_retention_days: 30,
      autonomy_blockers: ["no_tested_ats_adapter"],
      autonomy_prerequisites: [],
    });
    render(<SettingsPageClient candidateId="example_candidate" />);

    const toggle = await screen.findByRole("checkbox", {
      name: "Enable read-only scheduled discovery",
    });
    fireEvent.click(toggle);

    await waitFor(() =>
      expect(api.updateSettings).toHaveBeenCalledWith(
        {
          candidate_id: "example_candidate",
          discovery_enabled: false,
        },
        expect.stringMatching(/^settings-policy-/),
      ),
    );
    expect(await screen.findByText("Scheduled discovery paused")).toBeVisible();
  });

  it("persists browser-session retention through the backend contract", async () => {
    vi.mocked(api.updateSettings).mockResolvedValue({
      candidate_id: "example_candidate",
      automation_mode: "approval_required",
      discovery_enabled: true,
      emergency_stopped: false,
      allowed_ats_adapters: ["greenhouse"],
      tested_ats_adapters: [],
      dry_run_acceptance_passed: false,
      explicit_autonomy_confirmation: false,
      maximum_applications_per_day: 3,
      maximum_applications_per_week: 10,
      maximum_applications_per_company_30_days: 1,
      browser_session_retention_days: 90,
      autonomy_blockers: ["no_tested_ats_adapter"],
      autonomy_prerequisites: [],
    });
    render(<SettingsPageClient candidateId="example_candidate" />);

    fireEvent.change(
      await screen.findByRole("spinbutton", {
        name: "Confirmed browser-session retention",
      }),
      { target: { value: "90" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Save retention" }));

    await waitFor(() =>
      expect(api.updateSettings).toHaveBeenCalledWith(
        {
          candidate_id: "example_candidate",
          browser_session_retention_days: 90,
        },
        expect.stringMatching(/^settings-policy-/),
      ),
    );
  });

  it("reuses the policy key after an uncertain failure", async () => {
    vi.mocked(api.updateSettings)
      .mockRejectedValueOnce(new Error("Uncertain backend outcome."))
      .mockRejectedValueOnce(new Error("Uncertain backend outcome."));
    render(<SettingsPageClient candidateId="example_candidate" />);
    const toggle = await screen.findByRole("checkbox", {
      name: "Enable read-only scheduled discovery",
    });

    fireEvent.click(toggle);
    expect(await screen.findByText("Uncertain backend outcome.")).toBeVisible();
    fireEvent.click(toggle);
    await waitFor(() => expect(api.updateSettings).toHaveBeenCalledTimes(2));

    expect(vi.mocked(api.updateSettings).mock.calls[1][1]).toBe(
      vi.mocked(api.updateSettings).mock.calls[0][1],
    );
  });

  it("shows a blocked effective mode and direct fix when autonomous scope drifts", async () => {
    vi.mocked(api.settings).mockResolvedValue({
      ...(await api.settings("example_candidate")),
      automation_mode: "autonomous",
      tested_ats_adapters: ["greenhouse"],
      dry_run_acceptance_passed: true,
      autonomy_blockers: ["profile_not_approved", "explicit_confirmation_missing"],
      autonomy_prerequisites: [
        {
          code: "explicit_confirmation_missing",
          title: "Confirm the autonomous scope yourself",
          explanation: "Only the user can confirm this exact scope.",
          passed: false,
          resolution: "Resolve configuration first.",
          action_href: "#autonomy-confirmation",
          evidence_id: null,
          evidence_summary: null,
          evidenced_at: null,
        },
      ],
    });
    render(<SettingsPageClient candidateId="example_candidate" />);

    expect(await screen.findByRole("heading", { name: "approval required" })).toBeVisible();
    expect(screen.getByText(/Requested mode: autonomous/)).toBeVisible();
    expect(screen.getByText("Approve the candidate profile before enabling autonomy.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Resolve this blocker →" })).toHaveAttribute(
      "href",
      "/candidates/example_candidate/profile?section=candidate_controls",
    );
    expect(
      screen.getByRole("checkbox", { name: /understand these consequences/i }),
    ).toBeDisabled();
  });
});
