import { Suspense } from "react";
import { CompanyOverview } from "@/components/pages/CompanyOverview";
import { PageSkeleton } from "@/components/Page";
export default async function Page({ params }: { params: Promise<{ team: string }> }) {
  const { team } = await params;
  return <Suspense fallback={<PageSkeleton />}><CompanyOverview team={team} /></Suspense>;
}
