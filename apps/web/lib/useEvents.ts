"use client";

// SSE subscription to GET /tenants/{tenant}/events with exponential-backoff
// reconnect. Also receives events published on the local bus so mock demo
// actions update pages exactly like server events would.

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { busSubscribe } from "./bus";
import { isForcedMock, markLive, markMock } from "./mock-state";
import { EVENT_NAMES, type SSEEvent } from "./types";

export type EventsStatus = "idle" | "connecting" | "open" | "reconnecting" | "offline";

type Options = {
  enabled?: boolean;
  /** How many recent events to keep in the returned buffer. */
  keep?: number;
};

const ROUTE = "GET /tenants/{t}/events";

export function useEvents(tenant: string | null | undefined, onEvent?: (e: SSEEvent) => void, opts: Options = {}) {
  const { enabled = true, keep = 50 } = opts;
  const [status, setStatus] = useState<EventsStatus>(() => (isForcedMock() ? "offline" : "idle"));
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const handlerRef = useRef<typeof onEvent>(undefined);

  useEffect(() => {
    handlerRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!tenant || !enabled) return;
    let es: EventSource | null = null;
    let attempt = 0;
    let timer: number | undefined;
    let closed = false;

    const push = (e: SSEEvent) => {
      setEvents((prev) => [e, ...prev].slice(0, keep));
      handlerRef.current?.(e);
    };

    const parse = (m: MessageEvent, fallbackName?: string): SSEEvent | null => {
      try {
        const d = JSON.parse(String(m.data)) as Record<string, unknown>;
        if (d && typeof d === "object") {
          const event = typeof d.event === "string" ? d.event : (fallbackName ?? "message");
          const payload = (d.payload as Record<string, unknown> | undefined) ?? d;
          const ts = typeof d.ts === "number" ? d.ts : Date.now();
          return { event, payload, ts };
        }
      } catch {
        // not JSON: ignore keep-alives / comments
      }
      return null;
    };

    const connect = () => {
      if (closed) return;
      setStatus(attempt === 0 ? "connecting" : "reconnecting");
      try {
        es = new EventSource(api.eventsUrl(tenant));
      } catch {
        scheduleRetry();
        return;
      }
      es.onopen = () => {
        attempt = 0;
        setStatus("open");
        markLive(ROUTE);
      };
      es.onmessage = (m) => {
        const e = parse(m);
        if (e) push(e);
      };
      for (const name of EVENT_NAMES) {
        es.addEventListener(name, (m) => {
          const e = parse(m as MessageEvent, name);
          if (e) push(e);
        });
      }
      es.onerror = () => {
        es?.close();
        es = null;
        scheduleRetry();
      };
    };

    const scheduleRetry = () => {
      if (closed) return;
      attempt += 1;
      const delay = Math.min(30_000, 1000 * 2 ** Math.min(attempt, 5));
      if (attempt >= 3) {
        setStatus("offline");
      } else {
        setStatus("reconnecting");
      }
      timer = window.setTimeout(connect, delay);
    };

    if (isForcedMock()) {
      // status was initialised to "offline"; nothing to connect to
      markMock(ROUTE, "NEXT_PUBLIC_MOCK=1");
    } else {
      connect();
    }
    const unsub = busSubscribe(tenant, push);

    return () => {
      closed = true;
      es?.close();
      if (timer) window.clearTimeout(timer);
      unsub();
    };
  }, [tenant, enabled, keep]);

  const clear = useCallback(() => setEvents([]), []);

  return { status, events, clear };
}
