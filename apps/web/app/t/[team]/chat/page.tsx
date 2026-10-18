import { Suspense } from "react";
import { ChatPage } from "@/components/pages/ChatPage";
import { PageSkeleton } from "@/components/Page";

export const metadata = { title: "Ask Minutes" };

export default async function Page({ params }: { params: Promise<{ team: string }> }) {
  const { team } = await params;
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ChatPage team={team} />
    </Suspense>
  );
}
