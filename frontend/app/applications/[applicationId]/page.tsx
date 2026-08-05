import { ApplicationPageClient } from "./application-page-client";
import { resolveActiveCandidateId } from "@/lib/active-candidate-server";

export default async function ApplicationPage({ params, searchParams }: { params: Promise<{ applicationId: string }>; searchParams: Promise<{ candidate_id?: string }> }) {
  const [{ applicationId }, query] = await Promise.all([params, searchParams]);
  return <ApplicationPageClient applicationId={applicationId} candidateId={await resolveActiveCandidateId(query.candidate_id)} />;
}
