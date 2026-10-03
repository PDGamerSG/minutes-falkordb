// Local event bus. Mock mutations publish here so that pages subscribed through
// useEvents() react the same way they would to the server's SSE stream.

import type { SSEEvent } from "./types";

type Handler = (e: SSEEvent) => void;

const handlers = new Map<string, Set<Handler>>();

export function busSubscribe(tenant: string, h: Handler) {
  let set = handlers.get(tenant);
  if (!set) {
    set = new Set();
    handlers.set(tenant, set);
  }
  set.add(h);
  return () => {
    set?.delete(h);
  };
}

export function busPublish(tenant: string, event: string, payload: Record<string, unknown>) {
  const e: SSEEvent = { event, payload, ts: Date.now() };
  const set = handlers.get(tenant);
  if (!set) return;
  for (const h of set) {
    try {
      h(e);
    } catch {
      // a listener failing must not break the others
    }
  }
}
