import { JobPageClient } from "./job-page-client";
import { resolveActiveCandidateId } from "@/lib/active-candidate-server";

export default async function JobPage({ params, searchParams }: { params: Promise<{ jobId: string }>; searchParams: Promise<{ candidate_id?: string }> }) {
  const [{ jobId }, query] = await Promise.all([params, searchParams]);
  return <JobPageClient jobId={jobId} candidateId={await resolveActiveCandidateId(query.candidate_id)} />;
}
