import type { Metadata, Viewport } from "next";
import "./globals.css";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import { AppShell } from "@/components/AppShell";
import { OverlayProvider } from "@/components/Overlays";

export const metadata: Metadata = {
  title: { default: "Minutes", template: "%s · Minutes" },
  description: "Shared, time-aware memory for agent teams on FalkorDB.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  colorScheme: "light dark",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">
        <TooltipProvider>
          <OverlayProvider>
            <AppShell>{children}</AppShell>
          </OverlayProvider>
          <Toaster position="bottom-right" />
        </TooltipProvider>
      </body>
    </html>
  );
}
