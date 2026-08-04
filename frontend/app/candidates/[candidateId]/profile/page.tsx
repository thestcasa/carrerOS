import { ProfilePageClient } from "./profile-page-client";
import type { EditableSection } from "@/lib/types";

export default async function ProfilePage({
  params,
  searchParams,
}: {
  params: Promise<{ candidateId: string }>;
  searchParams: Promise<{ section?: string }>;
}) {
  const [{ candidateId }, query] = await Promise.all([params, searchParams]);
  return <ProfilePageClient candidateId={candidateId} initialSection={query.section as EditableSection | undefined} />;
}
