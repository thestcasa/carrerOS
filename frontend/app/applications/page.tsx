import { ApplicationsPageClient } from "./applications-page-client";
import { resolveActiveCandidateId } from "@/lib/active-candidate-server";

export default async function ApplicationsPage({ searchParams }: { searchParams: Promise<{ candidate_id?: string }> }) {
  const query = await searchParams;
  return <ApplicationsPageClient candidateId={await resolveActiveCandidateId(query.candidate_id)} />;
}
