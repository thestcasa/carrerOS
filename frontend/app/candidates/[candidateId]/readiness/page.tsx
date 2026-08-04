import { ReadinessPageClient } from "./readiness-page-client";

export default async function ReadinessPage({ params }: { params: Promise<{ candidateId: string }> }) {
  const { candidateId } = await params;
  return <ReadinessPageClient candidateId={candidateId} />;
}
