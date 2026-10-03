import { redirect } from "next/navigation";

export default async function Page({ params }: { params: Promise<{ team: string }> }) {
  const { team } = await params;
  redirect(`/t/${encodeURIComponent(team)}/sources`);
}
