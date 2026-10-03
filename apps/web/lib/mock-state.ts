"use client";

// Tracks which API routes fell back to mock data so the shell can show a
// "mock data" badge. A tiny external store; read with useMockState().

import { useSyncExternalStore } from "react";

export type Fallback = { route: string; reason: string; at: number };

type State = {
  fallbacks: Record<string, Fallback>;
  liveSeen: boolean;
  forced: boolean;
};

const FORCED =
  typeof process !== "undefined" &&
  (process.env.NEXT_PUBLIC_MOCK === "1" || process.env.NEXT_PUBLIC_MOCK === "true");

let state: State = { fallbacks: {}, liveSeen: false, forced: FORCED };
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

export function markMock(route: string, reason: string) {
  state = {
    ...state,
    fallbacks: { ...state.fallbacks, [route]: { route, reason, at: Date.now() } },
  };
  emit();
}

export function markLive(route: string) {
  const next = { ...state.fallbacks };
  const had = route in next;
  delete next[route];
  if (!had && state.liveSeen) return;
  state = { ...state, fallbacks: next, liveSeen: true };
  emit();
}

export function isForcedMock() {
  return state.forced;
}

export function getMockState() {
  return state;
}

export function subscribeMockState(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

const SERVER_SNAPSHOT: State = { fallbacks: {}, liveSeen: false, forced: FORCED };

export function useMockState() {
  return useSyncExternalStore(subscribeMockState, getMockState, () => SERVER_SNAPSHOT);
}

export function useIsMock() {
  const s = useMockState();
  return s.forced || Object.keys(s.fallbacks).length > 0;
}
