import { SecurityPageClient } from "./security-page-client";
import { resolveActiveCandidateId } from "@/lib/active-candidate-server";

export default async function SecurityPage({ searchParams }: { searchParams: Promise<{ candidate_id?: string }> }) {
  const query = await searchParams; return <SecurityPageClient candidateId={await resolveActiveCandidateId(query.candidate_id)} />;
}
