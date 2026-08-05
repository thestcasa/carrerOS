import { SecurityPageClient } from "./security-page-client";

export default async function SecurityPage({ searchParams }: { searchParams: Promise<{ candidate_id?: string }> }) {
  const query = await searchParams; return <SecurityPageClient candidateId={query.candidate_id ?? "example_candidate"} />;
}
