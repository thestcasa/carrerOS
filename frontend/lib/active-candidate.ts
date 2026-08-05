"use client";

import { useSyncExternalStore } from "react";
import { ACTIVE_CANDIDATE_COOKIE, validCandidateId } from "./active-candidate-common";

export function browserActiveCandidateId(): string | null {
  if (typeof document === "undefined") return "example_candidate";
  const query = new URLSearchParams(window.location.search);
  if (query.has("candidate_id")) return validCandidateId(query.get("candidate_id"));
  const value = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${ACTIVE_CANDIDATE_COOKIE}=`))
    ?.slice(ACTIVE_CANDIDATE_COOKIE.length + 1);
  try {
    return validCandidateId(value ? decodeURIComponent(value) : null) ?? "example_candidate";
  } catch {
    return "example_candidate";
  }
}

export function selectActiveCandidate(candidateId: string): void {
  const valid = validCandidateId(candidateId);
  if (!valid) throw new Error("candidate ID is invalid");
  document.cookie = `${ACTIVE_CANDIDATE_COOKIE}=${encodeURIComponent(valid)}; Path=/; Max-Age=31536000; SameSite=Strict`;
  window.dispatchEvent(new CustomEvent("careeros-active-candidate", { detail: valid }));
}

export function useActiveCandidateId(): string | null {
  return useSyncExternalStore(
    (notify) => {
      window.addEventListener("careeros-active-candidate", notify);
      window.addEventListener("popstate", notify);
      return () => {
        window.removeEventListener("careeros-active-candidate", notify);
        window.removeEventListener("popstate", notify);
      };
    },
    browserActiveCandidateId,
    () => "example_candidate",
  );
}
