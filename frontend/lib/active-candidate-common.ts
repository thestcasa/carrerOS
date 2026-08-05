export const ACTIVE_CANDIDATE_COOKIE = "careeros_active_candidate";
const CANDIDATE_ID = /^[a-z][a-z0-9_]{2,63}$/;

export function validCandidateId(value: string | null | undefined): string | null {
  return value && CANDIDATE_ID.test(value) ? value : null;
}
