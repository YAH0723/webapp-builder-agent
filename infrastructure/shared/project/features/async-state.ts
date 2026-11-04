export type AsyncState<T> = {status: "idle"} | {status: "pending"}
  | {status: "success"; data: T} | {status: "error"; error: Error};
