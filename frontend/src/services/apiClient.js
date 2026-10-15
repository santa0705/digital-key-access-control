/**
 * apiClient.js -- Central API client for Digital Key Access Control System
 *
 * Implements real HTTP communication with the FastAPI backend per docs/api-contract.md:
 * - Configurable base URL via Vite environment variable VITE_API_BASE_URL (defaults to http://localhost:8000)
 * - Standard JSON envelope parsing and error propagation via ApiError
 * - Bearer JWT authentication header injection without logging secrets or tokens
 * - Contract-supported operations for resources, access requests, approvals, revocations, and logs
 * - Absolute avoidance of silent fallback to mock data on API failures
 */

export class ApiError extends Error {
  constructor(message, code = 'error', status = 500, details = null) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

// Configurable Base URL: check import.meta.env (Vite) or process.env (Node test runner)
export function getApiBaseUrl() {
  if (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_API_BASE_URL) {
    return import.meta.env.VITE_API_BASE_URL.replace(/\/+$/, '');
  }
  if (typeof process !== 'undefined' && process.env && process.env.VITE_API_BASE_URL) {
    return process.env.VITE_API_BASE_URL.replace(/\/+$/, '');
  }
  return 'http://localhost:8000';
}

const STORAGE_KEY_TOKEN = 'dk_auth_token';
const STORAGE_KEY_USER = 'dk_auth_user';

// In-memory fallback if localStorage is disabled/unavailable (e.g. isolated test environments)
let memToken = null;
let memUser = null;

const authListeners = new Set();

export function subscribeAuth(callback) {
  authListeners.add(callback);
  return () => authListeners.delete(callback);
}

function notifyAuthChange(user) {
  for (const listener of authListeners) {
    try {
      listener(user);
    } catch {
      // Ignore listener error
    }
  }
}

export function getStoredToken() {
  try {
    if (typeof localStorage !== 'undefined') {
      return localStorage.getItem(STORAGE_KEY_TOKEN) || memToken;
    }
  } catch {
    // Ignore storage access error
  }
  return memToken;
}

export function setStoredToken(token) {
  memToken = token;
  try {
    if (typeof localStorage !== 'undefined') {
      if (token) {
        localStorage.setItem(STORAGE_KEY_TOKEN, token);
      } else {
        localStorage.removeItem(STORAGE_KEY_TOKEN);
      }
    }
  } catch {
    // Ignore storage access error
  }
}

export function getStoredUser() {
  try {
    if (typeof localStorage !== 'undefined') {
      const raw = localStorage.getItem(STORAGE_KEY_USER);
      if (raw) return JSON.parse(raw);
    }
  } catch {
    // Ignore parse error
  }
  return memUser;
}

export function setStoredUser(user) {
  memUser = user;
  try {
    if (typeof localStorage !== 'undefined') {
      if (user) {
        localStorage.setItem(STORAGE_KEY_USER, JSON.stringify(user));
      } else {
        localStorage.removeItem(STORAGE_KEY_USER);
      }
    }
  } catch {
    // Ignore storage access error
  }
  notifyAuthChange(user);
}

export function clearSession() {
  setStoredToken(null);
  setStoredUser(null);
}

export function isAuthenticated() {
  return Boolean(getStoredToken());
}

/**
 * Low-level request wrapper executing against FastAPI backend.
 * Never logs credentials, bearer tokens, or response bodies containing keys.
 */
export async function request(path, options = {}) {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}${path.startsWith('/') ? path : `/${path}`}`;

  const headers = {
    Accept: 'application/json',
    ...(options.headers || {})
  };

  const token = getStoredToken();
  if (token && !headers.Authorization && !headers.authorization) {
    headers.Authorization = `Bearer ${token}`;
  }

  let body = options.body;
  if (body && typeof body === 'object' && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(url, {
      ...options,
      headers,
      body
    });
  } catch (networkError) {
    throw new ApiError(
      `Network request failed: ${networkError.message}. Ensure backend is running at ${baseUrl}`,
      'network_error',
      0,
      networkError
    );
  }

  // Parse JSON or text response
  let data = null;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    try {
      data = await response.json();
    } catch {
      data = null;
    }
  } else if (response.status !== 204) {
    try {
      data = await response.text();
    } catch {
      data = null;
    }
  }

  if (!response.ok) {
    const errorEnvelope = data && typeof data === 'object' && data.error ? data.error : null;
    const code = errorEnvelope?.code || `http_${response.status}`;
    const message = errorEnvelope?.message || (typeof data === 'string' && data ? data : response.statusText || 'Request failed');

    // Handle 401 Unauthorized (session expired or invalid credentials)
    if (response.status === 401 && code === 'unauthorized') {
      clearSession();
    }

    throw new ApiError(message, code, response.status, data);
  }

  return data;
}

// ---------------------------------------------------------------------------
// High-Level Contract Endpoints
// ---------------------------------------------------------------------------

export const apiClient = {
  // Base & Session
  getBaseUrl: getApiBaseUrl,
  getStoredUser,
  getStoredToken,
  isAuthenticated,
  clearSession,
  subscribeAuth,

  /**
   * POST /auth/login (Contract 5.1)
   */
  async login({ email, password }) {
    if (!email || !password) {
      throw new ApiError('Email and password are required.', 'validation_error', 422);
    }
    const data = await request('/auth/login', {
      method: 'POST',
      body: {
        email: email.trim().toLowerCase(),
        password
      }
    });

    if (data?.access_token) {
      setStoredToken(data.access_token);
      setStoredUser(data.user);
    }
    return data;
  },

  /**
   * Log out and clear session state
   */
  logout() {
    clearSession();
  },

  /**
   * GET /resources (Contract 5.2)
   */
  async getResources() {
    return request('/resources', { method: 'GET' });
  },

  /**
   * POST /access-requests (Contract 5.2)
   */
  async createAccessRequest({ resource_id, start_at, end_at, purpose }) {
    return request('/access-requests', {
      method: 'POST',
      body: {
        resource_id: Number(resource_id),
        start_at,
        end_at,
        purpose: purpose ? purpose.trim() : null
      }
    });
  },

  /**
   * GET /access-requests/me (Contract 5.2)
   */
  async getMyAccessRequests() {
    return request('/access-requests/me', { method: 'GET' });
  },

  /**
   * GET /access-requests/{id}/pin (Contract 5.2)
   * Plaintext PIN must be handled transiently and never persisted to storage or logged.
   */
  async revealPin(requestId) {
    return request(`/access-requests/${requestId}/pin`, { method: 'GET' });
  },

  /**
   * GET /admin/access-requests (Contract 5.3)
   */
  async getAdminAccessRequests(statusFilter = 'all') {
    const query = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : '';
    return request(`/admin/access-requests${query}`, { method: 'GET' });
  },

  /**
   * POST /admin/access-requests/{id}/approve (Contract 5.3)
   * Maps frontend replaceExisting -> backend replace_existing
   */
  async approveAccessRequest(id, { note = '', replaceExisting = false } = {}) {
    return request(`/admin/access-requests/${id}/approve`, {
      method: 'POST',
      body: {
        note: note ? note.trim() : null,
        replace_existing: Boolean(replaceExisting)
      }
    });
  },

  /**
   * POST /admin/access-requests/{id}/reject (Contract 5.3)
   */
  async rejectAccessRequest(id, { note = '' } = {}) {
    return request(`/admin/access-requests/${id}/reject`, {
      method: 'POST',
      body: {
        note: note ? note.trim() : null
      }
    });
  },

  /**
   * POST /admin/credentials/{id}/revoke (Contract 5.3)
   */
  async revokeCredential(id, { note = '' } = {}) {
    return request(`/admin/credentials/${id}/revoke`, {
      method: 'POST',
      body: {
        note: note ? note.trim() : null
      }
    });
  },

  /**
   * GET /admin/logs (Contract 5.3)
   */
  async getAdminLogs({ limit = 100, source = 'all' } = {}) {
    const params = new URLSearchParams();
    if (limit) params.set('limit', String(limit));
    if (source && source !== 'all') params.set('source', source);
    const queryString = params.toString() ? `?${params.toString()}` : '';
    return request(`/admin/logs${queryString}`, { method: 'GET' });
  },

  /**
   * GET /admin/nodes (Contract 5.3)
   */
  async getAdminNodes() {
    return request('/admin/nodes', { method: 'GET' });
  }
};
