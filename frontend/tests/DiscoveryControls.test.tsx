import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DiscoveryControls } from "@/components/DiscoveryControls";
import { api } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: {
      ...original.api,
      discoverJobs: vi.fn(),
      discoverySources: vi.fn(),
      createDiscoverySource: vi.fn(),
      updateDiscoverySource: vi.fn(),
    },
  };
});

const source = {
  source_id: "source-1",
  candidate_id: "example_candidate",
  provider: "greenhouse" as const,
  company: "Fictional Labs",
  company_domain: "fictional.invalid",
  board_token: "fictional",
  enabled: true,
  cadence_minutes: 60,
  next_run_at: "2026-08-05T11:00:00Z",
  last_success_at: "2026-08-05T10:00:00Z",
  last_error: null,
  last_status: "completed",
  last_discovered: 2,
  last_unchanged: 3,
};

describe("DiscoveryControls", () => {
  beforeEach(() => {
    vi.mocked(api.discoverJobs).mockReset();
    vi.mocked(api.discoverySources).mockReset();
    vi.mocked(api.discoverySources).mockResolvedValue([]);
    vi.mocked(api.createDiscoverySource).mockReset();
    vi.mocked(api.updateDiscoverySource).mockReset();
  });

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

  it("reuses a manual-discovery key after uncertainty and rotates it after confirmation", async () => {
    vi.mocked(api.discoverJobs)
      .mockRejectedValueOnce(new Error("connection interrupted"))
      .mockResolvedValue({ discovered: 1, unchanged: 0, job_ids: ["job-1"] });
    render(<DiscoveryControls candidateId="example_candidate" onComplete={vi.fn()} />);
    fireEvent.change(screen.getByRole("textbox", { name: /company$/i }), { target: { value: "Fictional Labs" } });
    fireEvent.change(screen.getByRole("textbox", { name: /official company domain/i }), { target: { value: "fictional.invalid" } });
    fireEvent.change(screen.getByRole("textbox", { name: /structured payloads/i }), { target: { value: '[{"id":"job-1"}]' } });
    const run = screen.getByRole("button", { name: /run discovery/i });

    fireEvent.click(run);
    await screen.findByRole("alert");
    fireEvent.click(run);
    await waitFor(() => expect(api.discoverJobs).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.discoverJobs).mock.calls[1][1]).toBe(
      vi.mocked(api.discoverJobs).mock.calls[0][1],
    );

    fireEvent.click(run);
    await waitFor(() => expect(api.discoverJobs).toHaveBeenCalledTimes(3));
    expect(vi.mocked(api.discoverJobs).mock.calls[2][1]).not.toBe(
      vi.mocked(api.discoverJobs).mock.calls[1][1],
    );
  });

  it("reuses source-create and source-toggle keys until each mutation is confirmed", async () => {
    vi.mocked(api.discoverySources).mockResolvedValue([source]);
    vi.mocked(api.createDiscoverySource)
      .mockRejectedValueOnce(new Error("connection interrupted"))
      .mockResolvedValue(source);
    vi.mocked(api.updateDiscoverySource)
      .mockRejectedValueOnce(new Error("connection interrupted"))
      .mockResolvedValueOnce({ ...source, enabled: false })
      .mockResolvedValueOnce(source);
    render(<DiscoveryControls candidateId="example_candidate" onComplete={vi.fn()} />);
    fireEvent.change(screen.getByRole("textbox", { name: /company$/i }), { target: { value: source.company } });
    fireEvent.change(screen.getByRole("textbox", { name: /official company domain/i }), { target: { value: source.company_domain } });
    fireEvent.change(screen.getByRole("textbox", { name: /public board token/i }), { target: { value: source.board_token } });
    const schedule = screen.getByRole("button", { name: /schedule source/i });

    fireEvent.click(schedule);
    await screen.findByRole("alert");
    fireEvent.click(schedule);
    await waitFor(() => expect(api.createDiscoverySource).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.createDiscoverySource).mock.calls[1][2]).toBe(
      vi.mocked(api.createDiscoverySource).mock.calls[0][2],
    );
    fireEvent.click(schedule);
    await waitFor(() => expect(api.createDiscoverySource).toHaveBeenCalledTimes(3));
    expect(vi.mocked(api.createDiscoverySource).mock.calls[2][2]).not.toBe(
      vi.mocked(api.createDiscoverySource).mock.calls[1][2],
    );

    const pause = await screen.findByRole("button", { name: /pause source/i });
    fireEvent.click(pause);
    await screen.findByRole("alert");
    fireEvent.click(pause);
    await waitFor(() => expect(api.updateDiscoverySource).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.updateDiscoverySource).mock.calls[1][3]).toBe(
      vi.mocked(api.updateDiscoverySource).mock.calls[0][3],
    );
    const enable = await screen.findByRole("button", { name: /enable source/i });
    fireEvent.click(enable);
    await waitFor(() => expect(api.updateDiscoverySource).toHaveBeenCalledTimes(3));
    expect(vi.mocked(api.updateDiscoverySource).mock.calls[2][3]).not.toBe(
      vi.mocked(api.updateDiscoverySource).mock.calls[1][3],
    );
  });

  it("shows durable scheduled source status", async () => {
    vi.mocked(api.discoverySources).mockResolvedValue([source]);
    render(<DiscoveryControls candidateId="example_candidate" onComplete={vi.fn()} />);
    expect((await screen.findByText(/Fictional Labs/)).closest("li")).toHaveTextContent("completed · 2 changed / 3 unchanged");
    expect(api.discoverySources).toHaveBeenCalledWith("example_candidate");
  });
});
