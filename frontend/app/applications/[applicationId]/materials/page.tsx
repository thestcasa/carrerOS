import { redirect } from "next/navigation";

export default async function MaterialsPage({ params, searchParams }: { params: Promise<{ applicationId: string }>; searchParams: Promise<{ candidate_id?: string }> }) {
  const [{ applicationId }, query] = await Promise.all([params, searchParams]);
  redirect(`/applications/${applicationId}?candidate_id=${encodeURIComponent(query.candidate_id ?? "example_candidate")}`);
}
