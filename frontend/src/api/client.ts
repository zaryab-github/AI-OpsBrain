import type { TokenResult } from "./types";

const BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  code: string;
  details?: { field: string; message: string }[];
  constructor(status: number, code: string, message: string, details?: { field: string; message: string }[]) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

let accessToken: string | null = null;
let refreshInFlight: Promise<TokenResult | null> | null = null;
const listeners = new Set<(session: TokenResult | null) => void>();

export function setAccessToken(token: string | null) {
  accessToken = token;
}
export function getAccessToken() {
  return accessToken;
}
/** Called whenever a silent refresh succeeds or the session is lost. */
export function onSessionChange(fn: (session: TokenResult | null) => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

async function parseError(res: Response): Promise<ApiError> {
  try {
    const body = await res.json();
    const e = body?.error;
    if (e) return new ApiError(res.status, e.code ?? "error", e.message ?? res.statusText, e.details);
  } catch {
    /* not JSON */
  }
  return new ApiError(res.status, "http_error", res.statusText || `HTTP ${res.status}`);
}

/** Exchange the HttpOnly refresh cookie for a new access token. Concurrent callers share one request. */
export function refreshSession(): Promise<TokenResult | null> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const res = await fetch(`${BASE}/auth/refresh`, {
          method: "POST",
          headers: { "X-OBS-CSRF": "1" },
          credentials: "same-origin",
        });
        if (!res.ok) {
          setAccessToken(null);
          listeners.forEach((l) => l(null));
          return null;
        }
        const data = (await res.json()) as TokenResult;
        setAccessToken(data.access_token);
        listeners.forEach((l) => l(data));
        return data;
      } catch {
        return null;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | undefined | null>;
  auth?: boolean;
}

function buildUrl(path: string, query?: RequestOptions["query"]) {
  const params = new URLSearchParams();
  Object.entries(query ?? {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  });
  const qs = params.toString();
  return `${BASE}${path}${qs ? `?${qs}` : ""}`;
}

async function send(path: string, opts: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (opts.auth !== false && accessToken) headers.Authorization = `Bearer ${accessToken}`;
  return fetch(buildUrl(path, opts.query), {
    method: opts.method ?? "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    credentials: "same-origin",
  });
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  let res = await send(path, opts);
  if (res.status === 401 && opts.auth !== false) {
    const err = await parseError(res.clone());
    if (err.code === "token_expired" || err.code === "not_authenticated" || err.code === "token_invalid") {
      const renewed = await refreshSession();
      if (renewed) res = await send(path, opts);
    }
  }
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Download an authenticated file (e.g. the audit CSV) through the browser. */
export async function download(path: string, query: RequestOptions["query"], filename: string) {
  let res = await send(path, { query });
  if (res.status === 401 && (await refreshSession())) res = await send(path, { query });
  if (!res.ok) throw await parseError(res);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
