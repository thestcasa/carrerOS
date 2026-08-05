import { ApplicationsPageClient } from "./applications-page-client";

export default async function ApplicationsPage({ searchParams }: { searchParams: Promise<{ candidate_id?: string }> }) {
  const query = await searchParams;
  return <ApplicationsPageClient candidateId={query.candidate_id ?? "example_candidate"} />;
}
