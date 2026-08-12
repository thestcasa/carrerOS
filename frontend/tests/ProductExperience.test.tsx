import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApplicationTimeline } from "@/components/ApplicationTimeline";
import { AutopilotCard } from "@/components/AutopilotCard";
import { BottomSheet } from "@/components/BottomSheet";
import { ProfileOverview } from "@/components/ProfileOverview";
import { applicationStatus, automationStatus, matchStatus } from "@/lib/product-semantics";
import type { ApplicationEventView, CandidateDetail, DiscoverySourceView, SettingsView } from "@/lib/types";

const settings: SettingsView = {
  candidate_id: "example_candidate", automation_mode: "approval_required", discovery_enabled: true,
  emergency_stopped: false, allowed_ats_adapters: ["greenhouse"], tested_ats_adapters: [],
  dry_run_acceptance_passed: false, explicit_autonomy_confirmation: false,
  maximum_applications_per_day: 5, maximum_applications_per_week: 20,
  maximum_applications_per_company_30_days: 3, browser_session_retention_days: 30,
  autonomy_blockers: [], autonomy_prerequisites: [],
};

describe("candidate-facing product semantics", () => {
  it("maps every internal application state to readable product copy", () => {
    expect(applicationStatus("form_filling")).toMatchObject({ label: "Preparing submission", tone: "info" });
    expect(applicationStatus("human_action_required")).toMatchObject({ label: "Waiting for you", tone: "attention" });
    expect(applicationStatus("submitted").label).toBe("Awaiting confirmation");
    expect(applicationStatus("confirmed").label).toBe("Submitted");
    expect(applicationStatus("unknown_after_click")).toMatchObject({ label: "Outcome needs review", tone: "danger" });
  });

  it("uses real category state without inventing match claims", () => {
    expect(matchStatus(86, "target", "auto_apply").label).toBe("Excellent match");
    expect(matchStatus(86, "target", "prepare").label).toBe("Strong match");
    expect(matchStatus(65, "adjacent", "review").label).toBe("Possible match");
    expect(matchStatus(25, "target", "skip").label).toBe("Weak match");
    expect(matchStatus(null, null).label).toBe("Analysis pending");
  });

  it("gives emergency stop precedence and never implies resume", () => {
    const stopped = automationStatus({ ...settings, emergency_stopped: true }, 0);
    expect(stopped.label).toBe("Emergency stop active");
    expect(stopped.description).toMatch(/no new applications can be authorized/i);
  });
});

describe("responsive interaction primitives", () => {
  it("traps focus, closes on Escape, and returns focus to the trigger", () => {
    const onClose = vi.fn();
    function Example() {
      const [open, setOpen] = useState(false);
      return <><button onClick={() => setOpen(true)}>Open filters</button><BottomSheet open={open} title="Filters" onClose={() => { onClose(); setOpen(false); }}><button>Apply</button></BottomSheet></>;
    }
    render(<Example />);
    const trigger = screen.getByRole("button", { name: "Open filters" });
    trigger.focus();
    fireEvent.click(trigger);
    expect(screen.getByRole("button", { name: "Close Filters" })).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
    expect(trigger).toHaveFocus();
  });

  it("renders truthful Autopilot metrics and emergency management only", () => {
    const sources: DiscoverySourceView[] = [{
      source_id: "source-1", candidate_id: "example_candidate", provider: "greenhouse",
      company: "Fictional Labs", company_domain: "fictional.invalid", board_token: "fictional",
      enabled: true, cadence_minutes: 720, next_run_at: "2026-08-13T08:00:00Z",
      last_success_at: "2026-08-12T08:00:00Z", last_error: null, last_status: "completed",
      last_discovered: 2, last_unchanged: 1,
    }];
    render(<AutopilotCard candidateId="example_candidate" settings={{ ...settings, emergency_stopped: true }} actions={[]} jobs={[]} applications={[]} sources={sources} />);
    expect(screen.getByRole("heading", { name: "Emergency stop active" })).toBeVisible();
    expect(screen.getByText("1 active")).toBeVisible();
    expect(screen.getByRole("link", { name: /manage autopilot/i })).toHaveAttribute("href", "/settings?candidate_id=example_candidate");
    expect(screen.queryByRole("button", { name: /resume/i })).not.toBeInTheDocument();
  });

  it("builds application progress only from persisted events", () => {
    const events: ApplicationEventView[] = [
      { event_id: "event-1", event_type: "MATERIALS_GENERATED", from_state: "materials_generating", to_state: "review_pending", occurred_at: "2026-08-12T08:00:00Z", payload: {} },
      { event_id: "event-2", event_type: "BROWSER_DRY_RUN_QUEUED", from_state: "application_started", to_state: "form_filling", occurred_at: "2026-08-12T09:00:00Z", payload: {} },
    ];
    render(<ApplicationTimeline events={events} currentState="form_filling" />);
    expect(screen.getByText("Materials prepared")).toBeVisible();
    expect(screen.getByText("Preparing submission")).toBeVisible();
    expect(screen.getByText("Career OS is checking the application form.")).toBeVisible();
  });

  it("shows section-based readiness without fabricating a percentage label", () => {
    const detail: CandidateDetail = {
      candidate_id: "example_candidate", profile_version: "1.2.3",
      config: { manifest: { display_name: "Morgan Example" }, identity: { location: { display_value: "Exampleton" } } },
      readiness: {
        candidate_id: "example_candidate", status: "not_ready",
        issues: [{ code: "profile", message: "Review identity", domain: "identity", field_path: "identity", severity: "blocking" }],
        domains: [
          { domain: "identity", label: "Identity", status: "BLOCKED", field_path: "identity", issues: [] },
          { domain: "skills", label: "Skills", status: "READY", field_path: "skills", issues: [] },
        ],
        capabilities: [],
      },
    };
    render(<ProfileOverview detail={detail} />);
    expect(screen.getByRole("heading", { name: "Morgan Example" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "1 of 2 sections ready" })).toBeVisible();
    expect(screen.getByText("1 item needs your review.")).toBeVisible();
    expect(screen.getByRole("link", { name: /career preferences/i })).toHaveAttribute("href", expect.stringContaining("section=preferences"));
  });
});
