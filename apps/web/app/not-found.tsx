import Link from "next/link";
import { Database, House } from "lucide-react";
import { PageHeader } from "@/components/Page";
import { buttonVariants } from "@/components/ui/button";

export const metadata = { title: "Page not found" };

export default function NotFound() {
  return (
    <div className="space-y-4">
      <PageHeader title="Page not found." description="This address does not match a page in Minutes. Pick a workspace or go back to the home page." />
      <div className="flex flex-wrap gap-2">
        <Link href="/workspaces" className={buttonVariants()}>
          <Database /> Open workspaces
        </Link>
        <Link href="/" className={buttonVariants({ variant: "outline" })}>
          <House /> Home
        </Link>
      </div>
    </div>
  );
}
