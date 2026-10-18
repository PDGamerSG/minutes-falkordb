import { BoardPage } from "@/components/pages/BoardPage";

export const metadata = { title: "Agent board" };

export default async function Page({ params }: { params: Promise<{ team: string }> }) {
  const { team } = await params;
  return <BoardPage team={team} />;
}
