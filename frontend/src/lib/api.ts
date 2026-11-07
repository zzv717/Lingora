"use client";
/**
 * API client with JWT auth, transparent refresh-token rotation and Uzbek error messages.
 * All requests go through the same-origin /backend proxy (no CORS, no hardcoded hosts).
 */
import type { ApiErrorBody, TokenPair } from "./types";

const BASE = "/backend/api/v1";
const LS_ACCESS = "lingora.access";
const LS_REFRESH = "lingora.refresh";

export class ApiErr extends Error {
  code: string;
  status: number;
  details?: unknown;
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(LS_ACCESS);
}
export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(LS_REFRESH);
}
export function storeTokens(t: TokenPair) {
  localStorage.setItem(LS_ACCESS, t.access_token);
  localStorage.setItem(LS_REFRESH, t.refresh_token);
}
export function clearTokens() {
  localStorage.removeItem(LS_ACCESS);
  localStorage.removeItem(LS_REFRESH);
}

let refreshing: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (!getRefreshToken()) return false;
  refreshing ??= (async () => {
    try {
      const r = await fetch(`${BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: getRefreshToken() }),
      });
      if (!r.ok) return false;
      storeTokens(await r.json());
      return true;
    } catch {
      return false;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

export async function api<T = unknown>(
  path: string,
  opts: RequestInit & { raw?: boolean } = {}
): Promise<T> {
  const doFetch = () => {
    const headers: Record<string, string> = { ...(opts.headers as Record<string, string>) };
    const token = getAccessToken();
    if (token) headers["authorization"] = `Bearer ${token}`;
    if (opts.body && !(opts.body instanceof FormData) && !headers["content-type"]) {
      headers["content-type"] = "application/json";
    }
    return fetch(`${BASE}${path}`, { ...opts, headers });
  };

  let res = await doFetch();
  if (res.status === 401 && (await tryRefresh())) {
    res = await doFetch();
  }
  if (opts.raw) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* non-json */
  }
  if (!res.ok) {
    const err = (body as ApiErrorBody)?.error;
    if (err?.code === "UNAUTHORIZED" || err?.code === "TOKEN_EXPIRED") {
      clearTokens();
      if (typeof window !== "undefined" && !location.pathname.startsWith("/login")) {
        location.href = "/login";
      }
    }
    throw new ApiErr(res.status, err?.code || "ERROR", err?.message_uz || `Xatolik (${res.status})`, err?.details);
  }
  return body as T;
}

export const get = <T>(path: string) => api<T>(path);
export const post = <T>(path: string, data?: unknown) =>
  api<T>(path, { method: "POST", body: data !== undefined ? JSON.stringify(data) : undefined });
export const put = <T>(path: string, data?: unknown) =>
  api<T>(path, { method: "PUT", body: data !== undefined ? JSON.stringify(data) : undefined });
export const patch = <T>(path: string, data?: unknown) =>
  api<T>(path, { method: "PATCH", body: data !== undefined ? JSON.stringify(data) : undefined });
export const del = <T>(path: string) => api<T>(path, { method: "DELETE" });
