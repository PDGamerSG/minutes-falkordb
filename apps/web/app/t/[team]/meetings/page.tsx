import { redirect } from "next/navigation";

// The Meetings page became the Meetings tab of Sources. Keep old links working.
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ team: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { team } = await params;
  const sp = await searchParams;
  const qs = new URLSearchParams();
  qs.set("tab", "meetings");
  for (const [k, v] of Object.entries(sp)) {
    if (typeof v === "string") qs.set(k, v);
  }
  redirect(`/t/${encodeURIComponent(team)}/sources?${qs.toString()}`);
}
