import { Suspense } from "react";
import { TimelinePage } from "@/components/pages/TimelinePage";
import { PageSkeleton } from "@/components/Page";

export const metadata = { title: "Timeline" };

export default async function Page({ params }: { params: Promise<{ team: string }> }) {
  const { team } = await params;
  return (
    <Suspense fallback={<PageSkeleton />}>
      <TimelinePage team={team} />
    </Suspense>
  );
}
