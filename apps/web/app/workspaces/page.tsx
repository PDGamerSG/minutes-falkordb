import type { Metadata } from "next";
import { WorkspaceDirectory } from "@/components/landing/WorkspaceDirectory";

export const metadata: Metadata = { title: "Workspaces" };

export default function WorkspacesPage() {
  return <WorkspaceDirectory />;
}
