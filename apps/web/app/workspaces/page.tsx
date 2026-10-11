import type { Metadata } from "next";
import { WorkspaceDirectory } from "@/components/workspace/WorkspaceDirectory";
export const metadata: Metadata = { title: "Workspaces" };
export default function WorkspacesPage() { return <WorkspaceDirectory />; }
