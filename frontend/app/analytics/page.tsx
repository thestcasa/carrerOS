import { AnalyticsPageClient } from "./analytics-page-client";
import { resolveActiveCandidateId } from "@/lib/active-candidate-server";

export default async function AnalyticsPage({ searchParams }: { searchParams: Promise<{ candidate_id?: string }> }) { const query = await searchParams; return <AnalyticsPageClient candidateId={await resolveActiveCandidateId(query.candidate_id)} />; }
