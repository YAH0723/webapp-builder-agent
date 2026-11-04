// Shared transport only. Business validation and response decoding belong to callers.
export class HttpError extends Error {
  constructor(public readonly status: number, public readonly data: unknown,
    public readonly method: string, public readonly path: string) {
    super(`Request failed (${status})`); this.name = "HttpError";
  }
}
export type JsonRequest = Omit<RequestInit, "body"> & { body?: unknown };
export async function requestJson<T = unknown>(path: string, options: JsonRequest = {}): Promise<T> {
  if (!path.startsWith("/") || path.startsWith("//") || path.includes("\\")) throw new Error("Use an application-relative request path");
  const method = (options.method ?? "GET").toUpperCase();
  if ((method === "GET" || method === "HEAD") && options.body !== undefined)
    throw new Error(`${method} requests cannot contain a JSON body`);
  const headers = new Headers(options.headers);
  if (options.body !== undefined && !headers.has("content-type")) headers.set("content-type", "application/json");
  const response = await fetch(path, {...options, method, headers,
    credentials: options.credentials ?? "same-origin",
    body: options.body === undefined ? undefined : JSON.stringify(options.body)});
  const text = await response.text();
  let data: unknown = text || undefined;
  if (text && response.headers.get("content-type")?.includes("json")) {
    try { data = JSON.parse(text); }
    catch { if (response.ok) throw new Error("Server returned invalid JSON"); }
  }
  if (!response.ok) throw new HttpError(response.status, data, method, path.split("?")[0]);
  // T is a compile-time convenience, not runtime schema validation.
  return data as T;
}
