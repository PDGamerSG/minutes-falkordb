import { BoardPage } from "@/components/pages/BoardPage";

export default async function Page({ params }: { params: Promise<{ team: string }> }) {
  const { team } = await params;
  return <BoardPage team={team} />;
}
