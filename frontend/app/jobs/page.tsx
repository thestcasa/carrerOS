import { JobsPageClient } from "./jobs-page-client";
import { resolveActiveCandidateId } from "@/lib/active-candidate-server";

export default async function JobsPage({
  searchParams,
}: {
  searchParams: Promise<{ candidate_id?: string }>;
}) {
  const query = await searchParams;
  return <JobsPageClient candidateId={await resolveActiveCandidateId(query.candidate_id)} />;
}
