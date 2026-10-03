"use client";

import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";

type State<T> = { data: T | undefined; error: Error | null; loading: boolean };

type Options = {
  enabled?: boolean;
  /** Poll interval in ms. */
  refreshMs?: number;
};

/**
 * Minimal async resource hook: fetch on mount and when `deps` change, optional
 * polling, manual refetch and local optimistic updates. The fetcher is read
 * through a ref so callers can pass inline closures.
 */
export function useResource<T>(fetcher: () => Promise<T>, deps: DependencyList, opts: Options = {}) {
  const { enabled = true, refreshMs } = opts;
  const [state, setState] = useState<State<T>>({ data: undefined, error: null, loading: enabled });
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);

  useEffect(() => {
    fetcherRef.current = fetcher;
  }, [fetcher]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const run = async () => {
      setState((s) => ({ ...s, loading: s.data === undefined }));
      try {
        const data = await fetcherRef.current();
        if (!cancelled) setState({ data, error: null, loading: false });
      } catch (e) {
        if (!cancelled) setState((s) => ({ data: s.data, error: e instanceof Error ? e : new Error(String(e)), loading: false }));
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick, enabled]);

  useEffect(() => {
    if (!refreshMs || !enabled) return;
    const id = window.setInterval(() => setTick((t) => t + 1), refreshMs);
    return () => window.clearInterval(id);
  }, [refreshMs, enabled]);

  const refetch = useCallback(() => setTick((t) => t + 1), []);
  const setData = useCallback((updater: T | ((prev: T | undefined) => T | undefined)) => {
    setState((s) => ({
      ...s,
      data: typeof updater === "function" ? (updater as (p: T | undefined) => T | undefined)(s.data) : updater,
    }));
  }, []);

  return { ...state, refetch, setData };
}
