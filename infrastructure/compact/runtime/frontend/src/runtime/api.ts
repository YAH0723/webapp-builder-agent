export class ApiError extends Error {
  constructor(readonly status: number, readonly body: unknown) {
    super(body && typeof body === "object" && "error" in body ? String(body.error) : `HTTP ${status}`);
  }
}
// Relative same-origin URLs, real server responses, cookies, and no automatic retries.
export async function api<T = unknown>(path: string, options: RequestInit & {json?: unknown} = {}): Promise<T> {
  if (!path.startsWith("/") || path.startsWith("//")) throw new Error("Use a same-origin API path");
  const {json, ...init} = options, headers = new Headers(init.headers);
  if (json !== undefined) headers.set("content-type", "application/json");
  const response = await fetch(path, {...init, headers, credentials: init.credentials ?? "same-origin",
    body: json === undefined ? init.body : JSON.stringify(json)});
  const text = response.status === 204 ? "" : await response.text();
  let body: unknown = text || undefined;
  if (text && response.headers.get("content-type")?.includes("json")) body = JSON.parse(text);
  if (!response.ok) throw new ApiError(response.status, body);
  return body as T;
}
