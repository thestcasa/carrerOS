import { ApplicationPageClient } from "./application-page-client";

export default async function ApplicationPage({ params, searchParams }: { params: Promise<{ applicationId: string }>; searchParams: Promise<{ candidate_id?: string }> }) {
  const [{ applicationId }, query] = await Promise.all([params, searchParams]);
  return <ApplicationPageClient applicationId={applicationId} candidateId={query.candidate_id ?? "example_candidate"} />;
}
