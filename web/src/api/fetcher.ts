export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const SAFE_METHODS = new Set(["GET", "HEAD"]);

async function errorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const { detail } = body;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) {
        return detail.map((d: { msg?: string }) => d.msg ?? JSON.stringify(d)).join("; ");
      }
    }
  } catch {
    // not JSON
  }
  return response.statusText || `HTTP ${response.status}`;
}

export function apiHeaders(method: string, headers?: HeadersInit): Headers {
  const result = new Headers(headers);
  if (!SAFE_METHODS.has(method.toUpperCase())) result.set("X-Requested-With", "linguini");
  return result;
}

export async function apiFetch<T>(url: string, init: RequestInit = {}): Promise<T> {
  const method = init.method ?? "GET";
  const response = await fetch(url, {
    ...init,
    headers: apiHeaders(method, init.headers),
    credentials: "same-origin",
  });
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response));
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export type ErrorType<_E> = ApiError;
