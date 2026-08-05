import { redirect } from "next/navigation";
import { resolveActiveCandidateId } from "@/lib/active-candidate-server";

export default async function MaterialsPage({ params, searchParams }: { params: Promise<{ applicationId: string }>; searchParams: Promise<{ candidate_id?: string }> }) {
  const [{ applicationId }, query] = await Promise.all([params, searchParams]);
  redirect(`/applications/${applicationId}?candidate_id=${encodeURIComponent(await resolveActiveCandidateId(query.candidate_id))}`);
}
