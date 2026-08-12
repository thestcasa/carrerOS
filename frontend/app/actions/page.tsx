import { ActionsPageClient } from "./actions-page-client";
import { resolveActiveCandidateId } from "@/lib/active-candidate-server";

export default async function ActionsPage({ searchParams }: { searchParams: Promise<{ candidate_id?: string }> }) {
  const query = await searchParams;
  return <ActionsPageClient candidateId={await resolveActiveCandidateId(query.candidate_id)} />;
}
