"use client";

// App-wide overlays (Why sheet, Email drawer) are rendered once by the shell.
// Any component can open them through this context without importing the
// overlay components themselves (avoids GraphView <-> WhyPanel cycles).

import { createContext, useContext } from "react";

export type OpenEmailArgs = {
  tenant: string;
  threadId?: string | null;
  subject?: string | null;
  messageId?: string | null;
};

export type OverlayApi = {
  openWhy: (tenant: string, nodeId: string) => void;
  openEmail: (args: OpenEmailArgs) => void;
};

export const OverlayContext = createContext<OverlayApi>({
  openWhy: () => {},
  openEmail: () => {},
});

export function useOverlays() {
  return useContext(OverlayContext);
}
