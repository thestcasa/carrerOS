import { ActionsPageClient } from "./actions-page-client";

export default async function ActionsPage({ searchParams }: { searchParams: Promise<{ candidate_id?: string }> }) {
  const query = await searchParams;
  return <ActionsPageClient candidateId={query.candidate_id ?? "example_candidate"} />;
}
