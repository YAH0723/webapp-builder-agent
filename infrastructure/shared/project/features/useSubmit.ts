import { useCallback, useEffect, useRef, useState } from "react";
import type { AsyncState } from "./async-state.js";

// One concurrent operation per hook instance. Repeated calls share its promise.
// Server-side idempotency, business validation, navigation and refresh are caller-owned.
export function useSubmit<T = unknown>() {
  const [state, setState] = useState<AsyncState<T>>({status: "idle"});
  const pending = useRef<Promise<T> | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const run = useCallback((action: () => Promise<T>): Promise<T> => {
    if (pending.current) return pending.current;
    setState({status: "pending"});
    const result = Promise.resolve().then(action).then(data => {
      if (mounted.current) setState({status: "success", data});
      return data;
    }, error => {
      if (mounted.current) setState({status: "error", error: error instanceof Error ? error : new Error(String(error))});
      throw error;
    }).finally(() => { if (pending.current === result) pending.current = null; });
    pending.current = result;
    return result;
  }, []);
  const reset = useCallback(() => { if (!pending.current) setState({status: "idle"}); }, []);
  return {state, run, reset, pending: state.status === "pending"};
}
