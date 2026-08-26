import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api/client";

type State<T> = { data: T | null; error: string | null; loading: boolean };

/** Runs `fetcher` on mount and whenever `deps` change. One shape for every
 * screen's loading/error/data trio instead of re-deriving it per page. */
export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []): State<T> & { reload: () => void } {
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);

  const load = useCallback(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null }));
    fetcher()
      .then((data) => {
        if (!cancelled) setState({ data, error: null, loading: false });
      })
      .catch((err) => {
        if (cancelled) return;
        const message = err instanceof ApiError ? String(err.detail) : (err as Error).message;
        setState({ data: null, error: message, loading: false });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  useEffect(() => load(), [load]);

  return { ...state, reload: () => setTick((t) => t + 1) };
}
