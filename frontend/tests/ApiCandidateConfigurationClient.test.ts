import { beforeEach, describe, expect, it, vi } from "vitest";

const session = {
  session_token: "fictional-session-token",
  csrf_token: "fictional-csrf-token",
  candidate_ids: ["portable_candidate"],
};

describe("candidate configuration portability API client", () => {
  beforeEach(() => {
    vi.resetModules();
    sessionStorage.clear();
    sessionStorage.setItem("careeros-local-session", JSON.stringify(session));
  });

  it("downloads the raw bundle and imports it with concurrency and replay guards", async () => {
    const bundle = "kind: careeros_candidate_configuration\n";
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(bundle, {
          status: 200,
          headers: { "Content-Type": "application/yaml" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            candidate_id: "portable_candidate",
            previous_version: "profile-v1",
            profile_version: "profile-v2",
            source_profile_version: "source-v3",
            source_sha256: "a".repeat(64),
            changed: true,
            imported_sections: ["identity"],
            readiness: {
              candidate_id: "portable_candidate",
              status: "ready",
              issues: [],
              domains: [],
              capabilities: [],
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("@/lib/api");

    await expect(
      api.exportCandidateConfiguration("portable_candidate", "yaml"),
    ).resolves.toBe(bundle);
    await expect(
      api.importCandidateConfiguration(
        "portable_candidate",
        {
          format: "yaml",
          content: bundle,
          expected_profile_version: "profile-v1",
        },
        "configuration-import-replay-key",
      ),
    ).resolves.toMatchObject({
      candidate_id: "portable_candidate",
      profile_version: "profile-v2",
    });

    expect(String(fetchMock.mock.calls[0][0])).toContain(
      "/api/candidates/portable_candidate/configuration-export?format=yaml",
    );
    const importRequest = fetchMock.mock.calls[1][1] as RequestInit;
    expect(importRequest.method).toBe("POST");
    expect(importRequest.headers).toMatchObject({
      "Idempotency-Key": "configuration-import-replay-key",
      "X-CSRF-Token": "fictional-csrf-token",
    });
    expect(JSON.parse(String(importRequest.body))).toEqual({
      format: "yaml",
      content: bundle,
      expected_profile_version: "profile-v1",
    });
  });
});
