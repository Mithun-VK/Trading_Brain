// Thin fetch wrapper for the TradingBrain API. Never throws -- callers get
// a discriminated result so pages can render a friendly message instead of
// crashing when the API isn't running or a resource doesn't exist yet.

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// Read server-side only (no NEXT_PUBLIC_ prefix), so the token is never
// shipped to the browser bundle. All dashboard fetches happen in server
// components, so this is the right place for it. Empty is fine: the API is
// open unless API_AUTH_TOKENS is set on it.
const API_TOKEN = process.env.TRADINGBRAIN_API_TOKEN ?? "";

function authHeaders(): Record<string, string> {
  return API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {};
}

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: string; status?: number };

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...authHeaders(), ...(init?.headers ?? {}) },
      cache: "no-store",
    });

    if (!response.ok) {
      let detail = response.statusText || `HTTP ${response.status}`;
      try {
        const body = (await response.json()) as { detail?: string };
        detail = body.detail ?? detail;
      } catch {
        // Response body wasn't JSON -- keep the statusText fallback.
      }
      if (response.status === 401) {
        detail =
          "The API rejected this request (401). Set TRADINGBRAIN_API_TOKEN in the " +
          "dashboard environment to a value from the API's API_AUTH_TOKENS.";
      }
      return { ok: false, error: detail, status: response.status };
    }

    if (response.status === 204) {
      return { ok: true, data: undefined as T };
    }
    return { ok: true, data: (await response.json()) as T };
  } catch (err) {
    return {
      ok: false,
      error: `Could not reach TradingBrain API at ${API_BASE_URL}. Is it running? (${
        err instanceof Error ? err.message : String(err)
      })`,
    };
  }
}

export function apiGet<T>(path: string): Promise<ApiResult<T>> {
  return apiFetch<T>(path);
}

export function apiPost<T>(path: string, body?: unknown): Promise<ApiResult<T>> {
  return apiFetch<T>(path, {
    method: "POST",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

export function apiDelete<T>(path: string): Promise<ApiResult<T>> {
  return apiFetch<T>(path, { method: "DELETE" });
}

/** Fetch several endpoints concurrently. Each result is independent, so one
 *  failing section does not blank the whole page. */
export function apiGetAll<T extends readonly unknown[]>(
  ...paths: { [K in keyof T]: string }
): Promise<{ [K in keyof T]: ApiResult<T[K]> }> {
  return Promise.all(paths.map((p) => apiGet(p))) as Promise<{
    [K in keyof T]: ApiResult<T[K]>;
  }>;
}
