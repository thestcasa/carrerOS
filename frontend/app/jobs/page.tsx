import { JobsPageClient } from "./jobs-page-client";

export default async function JobsPage({
  searchParams,
}: {
  searchParams: Promise<{ candidate_id?: string }>;
}) {
  const query = await searchParams;
  return <JobsPageClient candidateId={query.candidate_id ?? "example_candidate"} />;
}
