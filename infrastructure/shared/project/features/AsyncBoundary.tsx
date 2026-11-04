import type { ReactNode } from "react";
import type { AsyncState } from "./async-state.js";

// All visible wording, roles, empty-state rules and business rendering are caller-owned.
export function AsyncBoundary<T>({state, idle = null, pending, error, children}: {
  state: AsyncState<T>; idle?: ReactNode; pending: ReactNode;
  error: (error: Error) => ReactNode; children: (data: T) => ReactNode;
}) {
  if (state.status === "pending") return <>{pending}</>;
  if (state.status === "error") return <>{error(state.error)}</>;
  if (state.status === "success") return <>{children(state.data)}</>;
  return <>{idle}</>;
}
