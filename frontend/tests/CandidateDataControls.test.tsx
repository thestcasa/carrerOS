import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CandidateDataControls } from "@/components/CandidateDataControls";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    exportCandidate: vi.fn(),
    exportCandidateConfiguration: vi.fn(),
    importCandidateConfiguration: vi.fn(),
    deletionStatus: vi.fn(),
    deleteCandidate: vi.fn(),
  },
}));

describe("CandidateDataControls", () => {
  beforeEach(() => {
    document.cookie = "careeros_active_candidate=delete_me; Path=/";
    window.history.replaceState({}, "", "/settings?candidate_id=delete_me");
    vi.clearAllMocks();
    vi.mocked(api.deletionStatus).mockRejectedValue({
      code: "deletion_not_found",
    });
  });

  it("requires exact candidate ID and redirects only after backend completion", async () => {
    vi.mocked(api.deleteCandidate).mockResolvedValue({
      candidate_id: "delete_me",
      status: "completed",
      deleted_rows: { candidate_settings: 1 },
      deleted_paths: ["candidate_configuration"],
      error_code: null,
      requested_at: "2026-08-05T10:00:00Z",
      completed_at: "2026-08-05T10:00:01Z",
    });
    render(
      <StrictMode>
        <CandidateDataControls
          candidateId="delete_me"
          profileVersion="profile-v1"
        />
      </StrictMode>,
    );
    const button = screen.getByRole("button", {
      name: "Delete candidate and archives",
    });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Delete_Me" },
    });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "delete_me" },
    });
    fireEvent.click(button);

    await waitFor(() => expect(window.location.pathname).toBe("/candidates"));
    expect(api.deleteCandidate).toHaveBeenCalledWith(
      "delete_me",
      "delete_me",
      expect.stringMatching(/^candidate-delete-/),
    );
    expect(document.cookie).not.toContain(
      "careeros_active_candidate=delete_me",
    );
  });

  it("keeps state on failure and reuses the same idempotency key", async () => {
    vi.mocked(api.deleteCandidate)
      .mockRejectedValueOnce(new Error("Deletion remains safely fenced."))
      .mockRejectedValueOnce(new Error("Deletion remains safely fenced."));
    render(
      <CandidateDataControls
        candidateId="delete_me"
        profileVersion="profile-v1"
      />,
    );
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "delete_me" },
    });
    const button = screen.getByRole("button", {
      name: "Delete candidate and archives",
    });
    fireEvent.click(button);
    expect(await screen.findByRole("alert")).toHaveTextContent("safely fenced");
    fireEvent.click(button);
    await waitFor(() => expect(api.deleteCandidate).toHaveBeenCalledTimes(2));

    const firstKey = vi.mocked(api.deleteCandidate).mock.calls[0][2];
    const secondKey = vi.mocked(api.deleteCandidate).mock.calls[1][2];
    expect(secondKey).toBe(firstKey);
    expect(window.location.pathname).toBe("/settings");
    expect(document.cookie).toContain("careeros_active_candidate=delete_me");
  });

  it("protects the fictional onboarding template", () => {
    render(
      <CandidateDataControls
        candidateId="example_candidate"
        profileVersion="profile-v1"
      />,
    );
    expect(screen.getByText(/protected from deletion/)).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Delete candidate and archives" }),
    ).not.toBeInTheDocument();
  });

  it("offers recovery when a durable deletion receipt is incomplete", async () => {
    vi.mocked(api.deletionStatus).mockResolvedValue({
      candidate_id: "delete_me",
      status: "failed",
      deleted_rows: { candidate_settings: 1 },
      deleted_paths: [],
      error_code: "candidate_deletion_failed",
      requested_at: "2026-08-05T10:00:00Z",
      completed_at: null,
    });

    render(
      <CandidateDataControls
        candidateId="delete_me"
        profileVersion="profile-v1"
      />,
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      "retry to finish it",
    );
    expect(
      screen.getByRole("button", { name: "Delete candidate and archives" }),
    ).toBeVisible();
  });

  it("downloads the complete portable manifest before revoking its URL", async () => {
    vi.mocked(api.exportCandidate).mockResolvedValue({
      schema_version: "1.0",
      candidate_id: "delete_me",
      created_at: "2026-08-05T10:00:00Z",
      files: [],
      database: {},
      manifest_sha256: "a".repeat(64),
    });
    const createUrl = vi.fn((blob: Blob) => {
      void blob;
      return "blob:portable-export";
    });
    const revokeUrl = vi.fn();
    vi.stubGlobal("URL", {
      createObjectURL: createUrl,
      revokeObjectURL: revokeUrl,
    });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    render(
      <CandidateDataControls
        candidateId="delete_me"
        profileVersion="profile-v1"
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Download candidate export" }),
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Portable export prepared",
    );
    expect(api.exportCandidate).toHaveBeenCalledWith("delete_me");
    expect(createUrl).toHaveBeenCalledWith(expect.any(Blob));
    const blob = createUrl.mock.calls[0][0] as Blob;
    const blobText = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(reader.error);
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(blob);
    });
    expect(blobText).toContain('"manifest_sha256": "aaaaaaaa');
    expect(click).toHaveBeenCalledOnce();
    await waitFor(() =>
      expect(revokeUrl).toHaveBeenCalledWith("blob:portable-export"),
    );
    click.mockRestore();
    vi.unstubAllGlobals();
  });

  it("downloads configuration-only JSON and YAML bundles distinctly", async () => {
    vi.mocked(api.exportCandidateConfiguration)
      .mockResolvedValueOnce('{"kind":"careeros_candidate_configuration"}\n')
      .mockResolvedValueOnce("kind: careeros_candidate_configuration\n");
    const createUrl = vi
      .fn()
      .mockReturnValueOnce("blob:configuration-json")
      .mockReturnValueOnce("blob:configuration-yaml");
    const revokeUrl = vi.fn();
    vi.stubGlobal("URL", {
      createObjectURL: createUrl,
      revokeObjectURL: revokeUrl,
    });
    const downloads: string[] = [];
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        downloads.push(this.download);
      });
    render(
      <CandidateDataControls
        candidateId="delete_me"
        profileVersion="profile-v1"
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Download configuration JSON" }),
    );
    await waitFor(() =>
      expect(api.exportCandidateConfiguration).toHaveBeenCalledWith(
        "delete_me",
        "json",
      ),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Download configuration YAML" }),
    );
    await waitFor(() =>
      expect(api.exportCandidateConfiguration).toHaveBeenCalledWith(
        "delete_me",
        "yaml",
      ),
    );

    expect(downloads).toEqual([
      "delete_me-configuration.json",
      "delete_me-configuration.yaml",
    ]);
    expect(screen.getByText(/do not restore workflow records/i)).toBeVisible();
    click.mockRestore();
    vi.unstubAllGlobals();
  });

  it("imports a bounded UTF-8 configuration against the current version", async () => {
    vi.mocked(api.importCandidateConfiguration)
      .mockResolvedValueOnce({
        candidate_id: "delete_me",
        previous_version: "profile-v1",
        profile_version: "profile-v2",
        source_profile_version: "source-v4",
        source_sha256: "b".repeat(64),
        changed: true,
        imported_sections: ["identity", "preferences"],
        readiness: {
          candidate_id: "delete_me",
          status: "ready",
          issues: [],
          domains: [],
          capabilities: [],
        },
      })
      .mockResolvedValueOnce({
        candidate_id: "delete_me",
        previous_version: "profile-v2",
        profile_version: "profile-v3",
        source_profile_version: "source-v5",
        source_sha256: "c".repeat(64),
        changed: true,
        imported_sections: ["identity"],
        readiness: {
          candidate_id: "delete_me",
          status: "ready",
          issues: [],
          domains: [],
          capabilities: [],
        },
      });
    render(
      <CandidateDataControls
        candidateId="delete_me"
        profileVersion="profile-v1"
      />,
    );
    const picker = screen.getByLabelText(/Configuration bundle/);
    fireEvent.change(picker, {
      target: {
        files: [new File(["kind: test\n"], "candidate.yaml", { type: "text/yaml" })],
      },
    });
    expect(await screen.findByText("Selected candidate.yaml")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Import configuration" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "profile version profile-v2",
    );
    expect(api.importCandidateConfiguration).toHaveBeenCalledWith(
      "delete_me",
      {
        format: "yaml",
        content: "kind: test\n",
        expected_profile_version: "profile-v1",
      },
      expect.stringMatching(/^candidate-configuration-import-/),
    );
    const firstKey = vi.mocked(api.importCandidateConfiguration).mock.calls[0][2];

    fireEvent.change(picker, {
      target: {
        files: [new File(["{\"kind\":\"test\"}"], "candidate.json")],
      },
    });
    expect(await screen.findByText("Selected candidate.json")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Import configuration" }));
    await waitFor(() =>
      expect(api.importCandidateConfiguration).toHaveBeenCalledTimes(2),
    );
    expect(vi.mocked(api.importCandidateConfiguration).mock.calls[1][1]).toEqual({
      format: "json",
      content: '{"kind":"test"}',
      expected_profile_version: "profile-v2",
    });
    expect(vi.mocked(api.importCandidateConfiguration).mock.calls[1][2]).not.toBe(
      firstKey,
    );
  });

  it("retains the configuration import key after an uncertain error", async () => {
    vi.mocked(api.importCandidateConfiguration)
      .mockRejectedValueOnce(new Error("Import outcome is uncertain."))
      .mockRejectedValueOnce(new Error("Import outcome is uncertain."));
    render(
      <CandidateDataControls
        candidateId="delete_me"
        profileVersion="profile-v1"
      />,
    );
    fireEvent.change(screen.getByLabelText(/Configuration bundle/), {
      target: { files: [new File(["{}"], "candidate.json")] },
    });
    expect(await screen.findByText("Selected candidate.json")).toBeVisible();
    const button = screen.getByRole("button", { name: "Import configuration" });
    fireEvent.click(button);
    expect(await screen.findByRole("alert")).toHaveTextContent("uncertain");
    fireEvent.click(button);
    await waitFor(() =>
      expect(api.importCandidateConfiguration).toHaveBeenCalledTimes(2),
    );
    expect(vi.mocked(api.importCandidateConfiguration).mock.calls[1][2]).toBe(
      vi.mocked(api.importCandidateConfiguration).mock.calls[0][2],
    );
  });

  it("rejects unsupported and oversized configuration files before upload", async () => {
    render(
      <CandidateDataControls
        candidateId="delete_me"
        profileVersion="profile-v1"
      />,
    );
    const picker = screen.getByLabelText(/Configuration bundle/);
    fireEvent.change(picker, {
      target: { files: [new File(["plain text"], "candidate.txt")] },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      ".json, .yaml, or .yml",
    );
    fireEvent.change(picker, {
      target: {
        files: [new File([new Uint8Array(MAX_FILE_BYTES)], "candidate.json")],
      },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "1 MiB or smaller",
    );
    expect(api.importCandidateConfiguration).not.toHaveBeenCalled();
  });
});

const MAX_FILE_BYTES = 1024 * 1024 + 1;
