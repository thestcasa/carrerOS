import { AnalyticsPageClient } from "./analytics-page-client";

export default async function AnalyticsPage({ searchParams }: { searchParams: Promise<{ candidate_id?: string }> }) { const query = await searchParams; return <AnalyticsPageClient candidateId={query.candidate_id ?? "example_candidate"} />; }
