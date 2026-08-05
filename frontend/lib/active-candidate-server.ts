import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import { ACTIVE_CANDIDATE_COOKIE, validCandidateId } from "./active-candidate-common";

export async function resolveActiveCandidateId(queryValue?: string): Promise<string> {
  if (queryValue !== undefined) {
    const fromQuery = validCandidateId(queryValue);
    if (!fromQuery) notFound();
    return fromQuery;
  }
  const cookieStore = await cookies();
  return validCandidateId(cookieStore.get(ACTIVE_CANDIDATE_COOKIE)?.value) ?? "example_candidate";
}
