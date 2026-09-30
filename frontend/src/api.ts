// Single API client for STIP. Bearer token in localStorage, auto-redirect to
// login on 401. Relative URLs in production; VITE_API_URL override for dev.

const API_BASE: string =
  (import.meta.env.VITE_API_URL as string | undefined) ?? '';

export const TOKEN_KEY = 'stip_token';
export const REFRESH_KEY = 'stip_refresh';
export const DEVICE_KEY = 'stip_device';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setAuth(a: { access_token: string; refresh_token?: string; device_id?: number } | null) {
  if (a) {
    localStorage.setItem(TOKEN_KEY, a.access_token);
    if (a.refresh_token) localStorage.setItem(REFRESH_KEY, a.refresh_token);
    if (a.device_id !== undefined) localStorage.setItem(DEVICE_KEY, String(a.device_id));
  } else {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(DEVICE_KEY);
  }
}

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown) {
    super(`API ${status}`);
    this.status = status;
    this.body = body;
  }
}

function onUnauthorized() {
  setAuth(null);
  if (!window.location.hash.startsWith('#/login')) {
    window.location.hash = '#/login';
  }
  window.dispatchEvent(new CustomEvent('stip:unauthorized'));
}

async function req<T>(
  method: string,
  path: string,
  body?: unknown,
  opts?: { form?: FormData }
): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  let payload: BodyInit | undefined;
  if (opts?.form) {
    payload = opts.form;
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  const res = await fetch(API_BASE + path, { method, headers, body: payload });
  if (res.status === 401) {
    onUnauthorized();
    throw new ApiError(401, { detail: 'Session expired — please log in again.' });
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = text;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    /* keep raw text */
  }
  if (!res.ok) throw new ApiError(res.status, data);
  return data as T;
}

export const api = {
  get: <T>(path: string) => req<T>('GET', path),
  post: <T>(path: string, body?: unknown) => req<T>('POST', path, body),
  patch: <T>(path: string, body?: unknown) => req<T>('PATCH', path, body),
  put: <T>(path: string, body?: unknown) => req<T>('PUT', path, body),
  del: <T>(path: string, body?: unknown) => req<T>('DELETE', path, body),
  upload: <T>(path: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return req<T>('POST', path, undefined, { form });
  },
  wsUrl: () => {
    const token = getToken() ?? '';
    const base = API_BASE || window.location.origin;
    return base.replace(/^http/, 'ws') + '/ws?token=' + encodeURIComponent(token);
  },
  mediaUrl: (p?: string | null) => {
    if (!p) return '';
    if (p.startsWith('http')) return p;
    return API_BASE + p;
  },
};

export function apiErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const b = err.body as { detail?: unknown } | null;
    if (b && typeof b.detail === 'string') return b.detail;
    if (err.status === 400) return 'Request was rejected by the server.';
    if (err.status === 403) return 'You are not allowed to do that.';
    if (err.status === 404) return 'Not found.';
    if (err.status === 422) return 'Invalid input — check the fields and try again.';
    if (err.status >= 500) return 'Server error — please try again shortly.';
    return `Request failed (${err.status}).`;
  }
  return 'Network error — check your connection.';
}

export function uuid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}
