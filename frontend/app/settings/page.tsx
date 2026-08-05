import { SettingsPageClient } from "./settings-page-client";

export default async function SettingsPage({ searchParams }: { searchParams: Promise<{ candidate_id?: string }> }) { const query = await searchParams; return <SettingsPageClient candidateId={query.candidate_id ?? "example_candidate"} />; }
