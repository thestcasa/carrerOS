import { beforeEach, describe, expect, it, vi } from "vitest";

const session = {
  session_token: "fictional-session-token",
  csrf_token: "fictional-csrf-token",
  candidate_ids: ["delete_me"],
};

function jsonResponse(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("candidate deletion API client", () => {
  beforeEach(() => {
    vi.resetModules();
    sessionStorage.clear();
    sessionStorage.setItem("careeros-local-session", JSON.stringify(session));
  });

  it("retains the local session when the backend receipt is incomplete", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          candidate_id: "delete_me",
          status: "failed",
          deleted_rows: {},
          deleted_paths: [],
          error_code: "candidate_deletion_failed",
          requested_at: "2026-08-05T10:00:00Z",
          completed_at: null,
        }),
      ),
    );
    const { api } = await import("@/lib/api");

    await expect(
      api.deleteCandidate("delete_me", "delete_me", "delete-client-receipt"),
    ).rejects.toMatchObject({ code: "deletion_unconfirmed" });
    expect(sessionStorage.getItem("careeros-local-session")).not.toBeNull();
  });

  it("clears local state only after a matching completed receipt", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          candidate_id: "delete_me",
          status: "completed",
          deleted_rows: { candidate_settings: 1 },
          deleted_paths: ["candidate_configuration"],
          error_code: null,
          requested_at: "2026-08-05T10:00:00Z",
          completed_at: "2026-08-05T10:00:01Z",
        }),
      )
      .mockResolvedValueOnce(jsonResponse(session))
      .mockResolvedValueOnce(jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@/lib/api");

    await api.deleteCandidate(
      "delete_me",
      "delete_me",
      "delete-client-complete",
    );
    expect(sessionStorage.getItem("careeros-local-session")).toBeNull();
    await api.candidates();
    expect(String(fetchMock.mock.calls[1][0])).toContain(
      "/api/auth/local-session",
    );
  });

  it("validates recovered receipt identity and clears a completed session", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          candidate_id: "delete_me",
          status: "completed",
          deleted_rows: {},
          deleted_paths: [],
          error_code: null,
          requested_at: "2026-08-05T10:00:00Z",
          completed_at: "2026-08-05T10:00:01Z",
        }),
      ),
    );
    const { api } = await import("@/lib/api");

    await expect(api.deletionStatus("delete_me")).resolves.toMatchObject({
      candidate_id: "delete_me",
      status: "completed",
    });
    expect(sessionStorage.getItem("careeros-local-session")).toBeNull();
  });

  it("rejects a recovered receipt for a different candidate", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          candidate_id: "different_candidate",
          status: "completed",
          deleted_rows: {},
          deleted_paths: [],
          error_code: null,
          requested_at: "2026-08-05T10:00:00Z",
          completed_at: "2026-08-05T10:00:01Z",
        }),
      ),
    );
    const { api } = await import("@/lib/api");

    await expect(api.deletionStatus("delete_me")).rejects.toMatchObject({
      code: "deletion_receipt_mismatch",
    });
    expect(sessionStorage.getItem("careeros-local-session")).not.toBeNull();
  });
});
