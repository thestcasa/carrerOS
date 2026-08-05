import { SettingsPageClient } from "./settings-page-client";
import { resolveActiveCandidateId } from "@/lib/active-candidate-server";

export default async function SettingsPage({ searchParams }: { searchParams: Promise<{ candidate_id?: string }> }) { const query = await searchParams; return <SettingsPageClient candidateId={await resolveActiveCandidateId(query.candidate_id)} />; }
