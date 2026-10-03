import { SkillsPage } from "@/components/pages/SkillsPage";

export default async function Page({ params }: { params: Promise<{ team: string }> }) {
  const { team } = await params;
  return <SkillsPage team={team} />;
}
