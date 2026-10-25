const DEFAULT_API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api/v1';
const STORAGE_KEY = 'tierlense_api_base_url';

export function getApiBase() {
  const stored = typeof localStorage !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null;
  return normalizeApiBase(stored || DEFAULT_API_BASE);
}

export function normalizeApiBase(value) {
  const trimmed = String(value || DEFAULT_API_BASE).trim().replace(/\/+$/, '');
  if (!trimmed) return DEFAULT_API_BASE;
  return /\/api\/v\d+$/i.test(trimmed) ? trimmed : `${trimmed}/api/v1`;
}

export function setApiBase(value) {
  const normalized = normalizeApiBase(value);
  localStorage.setItem(STORAGE_KEY, normalized);
  return normalized;
}

export class ApiError extends Error {
  constructor(message, status = 0, payload = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

function readError(payload, fallback) {
  if (typeof payload === 'string' && payload.trim()) return payload;
  if (payload?.detail) {
    if (typeof payload.detail === 'string') return payload.detail;
    if (Array.isArray(payload.detail)) return payload.detail.map((item) => item.msg || JSON.stringify(item)).join('; ');
    return JSON.stringify(payload.detail);
  }
  return payload?.message || fallback;
}

export async function apiRequest(path, options = {}) {
  const url = `${getApiBase()}${path.startsWith('/') ? path : `/${path}`}`;
  const headers = new Headers(options.headers || {});
  if (options.body !== undefined && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  headers.set('Accept', 'application/json');

  let response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch (error) {
    throw new ApiError(`Could not reach the TierLense API at ${getApiBase()}. Check that the backend is running and the address is correct.`, 0, error);
  }

  const text = await response.text();
  let payload = null;
  if (text) {
    try { payload = JSON.parse(text); } catch { payload = text; }
  }
  if (!response.ok) {
    throw new ApiError(readError(payload, `Request failed (${response.status})`), response.status, payload);
  }
  return payload;
}

export function queryString(values = {}) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  });
  const encoded = params.toString();
  return encoded ? `?${encoded}` : '';
}

export async function checkApi() {
  const live = await apiRequest('/health/live');
  let ready = null;
  try { ready = await apiRequest('/health/ready'); } catch (error) { ready = { error: error.message }; }
  return { live, ready };
}
