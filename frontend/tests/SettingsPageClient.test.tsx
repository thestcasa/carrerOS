import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SettingsPageClient } from "@/app/settings/settings-page-client";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    settings: vi.fn(),
    updateSettings: vi.fn(),
    emergencyStop: vi.fn(),
  },
}));

describe("SettingsPageClient", () => {
  beforeEach(() => {
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
      autonomy_blockers: ["no_tested_ats_adapter", "dry_run_acceptance_not_passed"],
    });
  });

  it("cannot enable autonomous mode while backend blockers exist", async () => {
    render(<SettingsPageClient candidateId="example_candidate" />);

    expect(await screen.findByRole("button", { name: "autonomous" })).toBeDisabled();
    expect(screen.getByText("no tested ats adapter")).toBeInTheDocument();
    expect(api.updateSettings).not.toHaveBeenCalled();
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
      autonomy_blockers: ["no_tested_ats_adapter"],
    });
    render(<SettingsPageClient candidateId="example_candidate" />);

    const toggle = await screen.findByRole("checkbox", {
      name: "Enable read-only scheduled discovery",
    });
    fireEvent.click(toggle);

    await waitFor(() =>
      expect(api.updateSettings).toHaveBeenCalledWith({
        candidate_id: "example_candidate",
        discovery_enabled: false,
      }),
    );
    expect(await screen.findByText("Scheduled discovery paused")).toBeVisible();
  });
});
