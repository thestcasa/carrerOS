import { JobPageClient } from "./job-page-client";

export default async function JobPage({ params, searchParams }: { params: Promise<{ jobId: string }>; searchParams: Promise<{ candidate_id?: string }> }) {
  const [{ jobId }, query] = await Promise.all([params, searchParams]);
  return <JobPageClient jobId={jobId} candidateId={query.candidate_id ?? "example_candidate"} />;
}
