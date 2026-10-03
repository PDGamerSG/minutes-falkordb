import { Suspense } from "react";
import { SourcesPage } from "@/components/pages/SourcesPage";
import { PageSkeleton } from "@/components/Page";

export default async function Page({ params }: { params: Promise<{ team: string }> }) {
  const { team } = await params;
  return (
    <Suspense fallback={<PageSkeleton />}>
      <SourcesPage team={team} />
    </Suspense>
  );
}
