import { ReadinessPageClient } from "./readiness-page-client";
import { notFound } from "next/navigation";
import { validCandidateId } from "@/lib/active-candidate-common";

export default async function ReadinessPage({ params }: { params: Promise<{ candidateId: string }> }) {
  const { candidateId } = await params;
  if (!validCandidateId(candidateId)) notFound();
  return <ReadinessPageClient candidateId={candidateId} />;
}
