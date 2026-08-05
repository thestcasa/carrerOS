import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DiscoveryControls } from "@/components/DiscoveryControls";
import { api } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, api: { ...original.api, discoverJobs: vi.fn(), discoverySources: vi.fn() } };
});

describe("DiscoveryControls", () => {
  beforeEach(() => { vi.mocked(api.discoverJobs).mockReset(); vi.mocked(api.discoverySources).mockResolvedValue([]); });

  it("rejects an empty payload without sending a command", () => {
    render(<DiscoveryControls candidateId="example_candidate" onComplete={vi.fn()} />);
    fireEvent.change(screen.getByRole("textbox", { name: /company$/i }), { target: { value: "Fictional Labs" } });
    fireEvent.change(screen.getByRole("textbox", { name: /official company domain/i }), { target: { value: "fictional.invalid" } });
    fireEvent.click(screen.getByRole("button", { name: /run discovery/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/at least one/i);
    expect(api.discoverJobs).not.toHaveBeenCalled();
  });

  it("sends a candidate-scoped command and reports completion", async () => {
    vi.mocked(api.discoverJobs).mockResolvedValue({ discovered: 1, unchanged: 2, job_ids: ["job-1"] });
    const onComplete = vi.fn();
    render(<DiscoveryControls candidateId="example_candidate" onComplete={onComplete} />);
    fireEvent.change(screen.getByRole("textbox", { name: /company$/i }), { target: { value: "Fictional Labs" } });
    fireEvent.change(screen.getByRole("textbox", { name: /official company domain/i }), { target: { value: "fictional.invalid" } });
    fireEvent.change(screen.getByRole("textbox", { name: /structured payloads/i }), { target: { value: '[{"id":"job-1"}]' } });
    fireEvent.click(screen.getByRole("button", { name: /run discovery/i }));
    await waitFor(() => expect(onComplete).toHaveBeenCalledOnce());
    expect(api.discoverJobs).toHaveBeenCalledWith(expect.objectContaining({ candidate_id: "example_candidate", company_domain: "fictional.invalid" }), expect.any(String));
    expect(screen.getByText(/1 new or changed; 2 unchanged/i)).toBeInTheDocument();
  });

  it("shows durable scheduled source status", async () => {
    vi.mocked(api.discoverySources).mockResolvedValue([{ source_id: "source-1", candidate_id: "example_candidate", provider: "greenhouse", company: "Fictional Labs", company_domain: "fictional.invalid", board_token: "fictional", enabled: true, cadence_minutes: 60, next_run_at: "2026-08-05T11:00:00Z", last_success_at: "2026-08-05T10:00:00Z", last_error: null, last_status: "completed", last_discovered: 2, last_unchanged: 3 }]);
    render(<DiscoveryControls candidateId="example_candidate" onComplete={vi.fn()} />);
    expect((await screen.findByText(/Fictional Labs/)).closest("li")).toHaveTextContent("completed · 2 changed / 3 unchanged");
    expect(api.discoverySources).toHaveBeenCalledWith("example_candidate");
  });
});
