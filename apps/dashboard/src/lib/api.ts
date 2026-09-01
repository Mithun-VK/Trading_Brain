// Thin fetch wrapper for the TradingBrain API. Never throws -- callers get
// a discriminated result so pages can render a friendly message instead of
// crashing when the API isn't running or a resource doesn't exist yet.

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: string; status?: number };

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
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
