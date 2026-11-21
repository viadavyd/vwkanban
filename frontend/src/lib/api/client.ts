// Fetch wrapper for /api: JSON in/out, same-origin cookies, error envelope → ApiError.

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    /** Extra fields of the error object, e.g. an op reject's `op_id` and `current`. */
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Method = "GET" | "POST" | "PATCH" | "DELETE";

export async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
  if (body === undefined) return send<T>(method, path);
  return send<T>(method, path, JSON.stringify(body), "application/json");
}

/** A request whose body is sent as is (e.g. a CSV file as `text/csv`). */
export function requestRaw<T>(method: Method, path: string, body: Blob, type: string): Promise<T> {
  return send<T>(method, path, body, type);
}

async function send<T>(method: Method, path: string, body?: BodyInit, type?: string): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: {} };
  if (body !== undefined) {
    init.body = body;
    (init.headers as Record<string, string>)["Content-Type"] = type!;
  }
  let res: Response;
  try {
    res = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError(0, "network", "cannot reach the server");
  }
  if (res.ok) {
    return (res.status === 204 ? undefined : await res.json()) as T;
  }
  throw await toError(res);
}

async function toError(res: Response): Promise<ApiError> {
  if (res.status === 429) {
    return new ApiError(429, "rate_limited", "too many attempts, wait a minute");
  }
  try {
    const data = await res.json();
    const err = data?.error;
    if (err && typeof err.code === "string") {
      const { code, message, ...details } = err;
      return new ApiError(res.status, code, String(message ?? code), details);
    }
  } catch {
    // not JSON (e.g. an nginx error page)
  }
  return new ApiError(res.status, "error", `request failed (${res.status})`);
}
