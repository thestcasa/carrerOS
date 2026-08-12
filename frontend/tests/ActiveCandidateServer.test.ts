import { beforeEach, describe, expect, it, vi } from "vitest";

const navigation = vi.hoisted(() => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
}));
const headers = vi.hoisted(() => ({
  cookies: vi.fn(async () => ({ get: vi.fn(() => undefined) })),
}));

vi.mock("next/navigation", () => navigation);
vi.mock("next/headers", () => headers);

import { resolveActiveCandidateId } from "@/lib/active-candidate-server";

describe("server active candidate resolution", () => {
  beforeEach(() => vi.clearAllMocks());

  it("denies a present but malformed query instead of falling back", async () => {
    await expect(resolveActiveCandidateId("../wrong")).rejects.toThrow("NEXT_NOT_FOUND");
    expect(navigation.notFound).toHaveBeenCalledOnce();
    expect(headers.cookies).not.toHaveBeenCalled();
  });

  it("uses the safe default when neither query nor valid cookie is present", async () => {
    await expect(resolveActiveCandidateId()).resolves.toBe("example_candidate");
  });
});
