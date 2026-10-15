/**
 * adminApi.js -- Unified Frontend API Service
 *
 * Connects frontend UI components to real FastAPI endpoints via apiClient.
 * Adheres strictly to docs/api-contract.md:
 * - Live paths execute real HTTP requests against the backend.
 * - Silent fallback to mock data on API failures is strictly prohibited.
 * - Demo mode is supported ONLY when explicitly activated by user.
 * - Plaintext PINs are never persisted to storage or logged.
 */

import { apiClient, ApiError } from './apiClient.js';
import { INITIAL_ACCESS_REQUESTS, INITIAL_CREDENTIALS } from './mockData.js';
import { getEffectiveCredentialStatus } from '../utils/dateUtils.js';

const STORAGE_KEY_DEMO = 'dk_explicit_demo_mode';
const STORAGE_KEY_MOCK_REQUESTS = 'dk_mock_access_requests';
const STORAGE_KEY_MOCK_CREDS = 'dk_mock_credentials';

function isDemoActive() {
  try {
    if (typeof localStorage !== 'undefined') {
      return localStorage.getItem(STORAGE_KEY_DEMO) === 'true';
    }
  } catch {
    // Ignore storage read error
  }
  return false;
}

function loadStored(key, fallback) {
  try {
    if (typeof localStorage !== 'undefined') {
      const raw = localStorage.getItem(key);
      if (raw) return JSON.parse(raw);
    }
  } catch {
    // Ignore storage read error
  }
  return JSON.parse(JSON.stringify(fallback));
}

function saveStored(key, data) {
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(key, JSON.stringify(data));
    }
  } catch {
    // Ignore storage write error
  }
}

// In-memory mock cache for demo mode
let mockAccessRequests = loadStored(STORAGE_KEY_MOCK_REQUESTS, INITIAL_ACCESS_REQUESTS);
let mockCredentials = loadStored(STORAGE_KEY_MOCK_CREDS, INITIAL_CREDENTIALS);
let mockChangeSeqCounter = 50;

export const adminApi = {
  // Re-export core apiClient utilities
  ApiError,
  getBaseUrl: apiClient.getBaseUrl,
  getStoredUser: apiClient.getStoredUser,
  getStoredToken: apiClient.getStoredToken,
  isAuthenticated: apiClient.isAuthenticated,
  subscribeAuth: apiClient.subscribeAuth,

  /**
   * Check or toggle explicit demo mode.
   * Note: LIVE API IS THE DEFAULT. Demo mode must be explicitly turned on.
   */
  isDemoMode() {
    return isDemoActive();
  },

  setDemoMode(enabled) {
    try {
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem(STORAGE_KEY_DEMO, enabled ? 'true' : 'false');
      }
    } catch {
      // Ignore storage error
    }
  },

  /**
   * Reset mock data fixtures (only relevant in isolated demo mode)
   */
  resetMockData() {
    mockAccessRequests = JSON.parse(JSON.stringify(INITIAL_ACCESS_REQUESTS));
    mockCredentials = JSON.parse(JSON.stringify(INITIAL_CREDENTIALS));
    mockChangeSeqCounter = 50;
    saveStored(STORAGE_KEY_MOCK_REQUESTS, mockAccessRequests);
    saveStored(STORAGE_KEY_MOCK_CREDS, mockCredentials);
  },

  /**
   * POST /auth/login (Contract 5.1)
   */
  async login({ email, password }) {
    if (isDemoActive()) {
      if (password === 'invalid') {
        throw new ApiError('Invalid email or password.', 'invalid_credentials', 401);
      }
      const demoUser = {
        id: 1,
        email: email.trim().toLowerCase(),
        full_name: email.includes('admin') ? 'Administrator' : 'Test User',
        role: email.includes('admin') ? 'admin' : 'user'
      };
      const demoData = {
        access_token: 'demo_mock_jwt_token_hs256',
        token_type: 'bearer',
        expires_in: 28800,
        user: demoUser
      };
      apiClient.login = async () => demoData;
      return demoData;
    }

    return apiClient.login({ email, password });
  },

  /**
   * Logout and clear session
   */
  logout() {
    apiClient.logout();
  },

  /**
   * GET /resources (Contract 5.2)
   */
  async getResources() {
    if (isDemoActive()) {
      return [
        { id: 1, code: 'A', name: 'Locker A', kind: 'physical', is_active: true },
        { id: 2, code: 'B', name: 'Locker B', kind: 'physical', is_active: true }
      ];
    }
    return apiClient.getResources();
  },

  /**
   * POST /access-requests (Contract 5.2)
   */
  async createAccessRequest({ resource_id, start_at, end_at, purpose }) {
    if (isDemoActive()) {
      const newId = Math.max(100, ...mockAccessRequests.map((r) => r.id)) + 1;
      const newReq = {
        id: newId,
        resource: { id: resource_id, code: resource_id === 1 ? 'A' : 'B', name: `Locker ${resource_id}`, kind: 'physical' },
        user: { id: 2, full_name: 'Jane User' },
        start_at,
        end_at,
        purpose: purpose || null,
        status: 'pending',
        decision_note: null,
        decided_at: null,
        created_at: new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'),
        credential: null
      };
      mockAccessRequests = [newReq, ...mockAccessRequests];
      saveStored(STORAGE_KEY_MOCK_REQUESTS, mockAccessRequests);
      return newReq;
    }
    return apiClient.createAccessRequest({ resource_id, start_at, end_at, purpose });
  },

  /**
   * GET /access-requests/me (Contract 5.2)
   */
  async getMyAccessRequests() {
    if (isDemoActive()) {
      return mockAccessRequests.filter((r) => r.user?.id === 2 || r.user?.email === 'user@demo.local');
    }
    return apiClient.getMyAccessRequests();
  },

  /**
   * GET /access-requests/{id}/pin (Contract 5.2)
   * Plaintext PIN must be treated with high confidentiality:
   * never persisted to localStorage and never logged to console.
   */
  async revealPin(requestId) {
    if (isDemoActive()) {
      return {
        request_id: Number(requestId),
        resource_code: 'A',
        pin: '482916',
        valid_from: '2026-10-14T08:00:00Z',
        valid_until: '2026-10-14T09:00:00Z'
      };
    }
    return apiClient.revealPin(requestId);
  },

  /**
   * GET /admin/access-requests (Contract 5.3)
   */
  async getAccessRequests(statusFilter = 'all') {
    if (isDemoActive()) {
      if (!statusFilter || statusFilter === 'all') {
        return [...mockAccessRequests];
      }
      return mockAccessRequests.filter((r) => r.status === statusFilter);
    }
    return apiClient.getAdminAccessRequests(statusFilter);
  },

  /**
   * Check Rule R1: Find active credential on a given resource
   * In live mode, inspects the access requests returned by the backend.
   */
  async getActiveCredentialForResource(resourceCode) {
    if (isDemoActive()) {
      return (
        mockCredentials.find(
          (c) => c.resource?.code === resourceCode && c.status === 'active'
        ) || null
      );
    }

    // Live mode: fetch requests and find any active credential for this resource
    const requests = await apiClient.getAdminAccessRequests('all');
    for (const req of requests) {
      if (req.resource?.code === resourceCode && req.credential) {
        const effStatus = getEffectiveCredentialStatus(req.credential);
        if (effStatus === 'active') {
          return {
            id: req.credential.id,
            request_id: req.id,
            resource: req.resource,
            user: req.user,
            status: 'active',
            valid_from: req.credential.valid_from,
            valid_until: req.credential.valid_until
          };
        }
      }
    }
    return null;
  },

  /**
   * POST /admin/access-requests/{id}/approve (Contract 5.3)
   * Maps frontend replaceExisting -> backend replace_existing
   */
  async approveAccessRequest(id, { note = '', replaceExisting = false } = {}) {
    if (isDemoActive()) {
      const target = mockAccessRequests.find((r) => r.id === Number(id));
      if (!target) throw new ApiError(`Access request #${id} not found.`, 'not_found', 404);
      if (target.status !== 'pending') {
        throw new ApiError(`Request #${id} is already ${target.status}; only pending requests can be approved.`, 'invalid_state', 409);
      }

      const existingActive = mockCredentials.find(
        (c) => c.resource?.code === target.resource?.code && c.status === 'active'
      );

      if (existingActive && !replaceExisting) {
        const err = new ApiError(
          `Resource ${target.resource?.code} has active credential #${existingActive.id} (request #${existingActive.request_id}). Revoke it or approve with replace_existing.`,
          'active_credential_exists',
          409
        );
        err.existingCredential = existingActive;
        throw err;
      }

      const nowIso = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
      mockChangeSeqCounter += 1;

      if (existingActive && replaceExisting) {
        existingActive.status = 'revoked';
        existingActive.revoke_reason = 'superseded';
        existingActive.revoked_at = nowIso;
        existingActive.change_seq = mockChangeSeqCounter;
        const parentReq = mockAccessRequests.find((r) => r.id === existingActive.request_id);
        if (parentReq) parentReq.status = 'revoked';
        mockChangeSeqCounter += 1;
      }

      const newCredId = Math.max(100, ...mockCredentials.map((c) => c.id)) + 1;
      const newCredential = {
        id: newCredId,
        request_id: target.id,
        resource: { ...target.resource },
        user: { ...target.user },
        masked_pin: '••••••',
        credential_ref: `CR-${String(newCredId).padStart(3, '0')}`,
        valid_from: target.start_at,
        valid_until: target.end_at,
        status: 'active',
        revoke_reason: null,
        revoked_at: null,
        change_seq: mockChangeSeqCounter,
        created_at: nowIso,
        node_sync_state: 'anchored'
      };

      mockCredentials = [newCredential, ...mockCredentials];
      target.status = 'approved';
      target.decision_note = note.trim() || 'Approved by administrator';
      target.decided_at = nowIso;
      target.credential = {
        id: newCredential.id,
        status: 'active',
        valid_from: newCredential.valid_from,
        valid_until: newCredential.valid_until,
        revoke_reason: null
      };

      saveStored(STORAGE_KEY_MOCK_REQUESTS, mockAccessRequests);
      saveStored(STORAGE_KEY_MOCK_CREDS, mockCredentials);
      return { ...target };
    }

    return apiClient.approveAccessRequest(id, { note, replaceExisting });
  },

  /**
   * POST /admin/access-requests/{id}/reject (Contract 5.3)
   */
  async rejectAccessRequest(id, { note = '' } = {}) {
    if (isDemoActive()) {
      const target = mockAccessRequests.find((r) => r.id === Number(id));
      if (!target) throw new ApiError(`Access request #${id} not found.`, 'not_found', 404);
      if (target.status !== 'pending') {
        throw new ApiError(`Request #${id} is already ${target.status}; only pending requests can be rejected.`, 'invalid_state', 409);
      }
      const nowIso = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
      target.status = 'rejected';
      target.decision_note = note.trim() || 'Rejected by administrator';
      target.decided_at = nowIso;
      saveStored(STORAGE_KEY_MOCK_REQUESTS, mockAccessRequests);
      return { ...target };
    }

    return apiClient.rejectAccessRequest(id, { note });
  },

  /**
   * Derived Credentials Endpoint:
   * The backend contract (docs/api-contract.md) does not expose a standalone /admin/credentials endpoint.
   * Credentials are recovered from GET /admin/access-requests where .credential is present.
   * Note: CredentialSummary in the contract does not include change_seq or consumed_at;
   * change_seq is populated when revoking via POST /admin/credentials/{id}/revoke.
   */
  async getCredentials(statusFilter = 'all') {
    if (isDemoActive()) {
      if (!statusFilter || statusFilter === 'all') {
        return [...mockCredentials];
      }
      return mockCredentials.filter((c) => c.status === statusFilter);
    }

    // Live mode: Recover credentials from access requests
    const requests = await apiClient.getAdminAccessRequests('all');
    const creds = [];

    for (const req of requests) {
      if (req.credential) {
        const effStatus = getEffectiveCredentialStatus(req.credential);
        creds.push({
          id: req.credential.id,
          request_id: req.id,
          resource: req.resource,
          user: req.user,
          valid_from: req.credential.valid_from,
          valid_until: req.credential.valid_until,
          status: effStatus,
          revoke_reason: req.credential.revoke_reason,
          credential_ref: `CR-${String(req.credential.id).padStart(3, '0')}`,
          masked_pin: '••••••',
          created_at: req.created_at,
          // Contract gap: CredentialSummary does not expose change_seq or consumed_at
          change_seq: null,
          node_sync_state: 'anchored'
        });
      }
    }

    if (!statusFilter || statusFilter === 'all') {
      return creds;
    }
    return creds.filter((c) => c.status === statusFilter);
  },

  /**
   * POST /admin/credentials/{id}/revoke (Contract 5.3)
   */
  async revokeCredential(id, { note = '' } = {}) {
    if (isDemoActive()) {
      const target = mockCredentials.find((c) => c.id === Number(id));
      if (!target) throw new ApiError(`Credential #${id} not found.`, 'not_found', 404);
      if (target.status !== 'active') {
        throw new ApiError(`Credential #${id} is already in terminal status "${target.status}".`, 'invalid_state', 409);
      }
      const nowIso = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
      mockChangeSeqCounter += 1;
      target.status = 'revoked';
      target.revoke_reason = 'admin';
      target.revoked_at = nowIso;
      target.change_seq = mockChangeSeqCounter;
      target.admin_revoke_note = note.trim() || 'Admin manual revocation';

      const parentReq = mockAccessRequests.find((r) => r.id === target.request_id);
      if (parentReq) {
        parentReq.status = 'revoked';
        if (parentReq.credential) {
          parentReq.credential.status = 'revoked';
          parentReq.credential.revoke_reason = 'admin';
        }
      }

      saveStored(STORAGE_KEY_MOCK_REQUESTS, mockAccessRequests);
      saveStored(STORAGE_KEY_MOCK_CREDS, mockCredentials);
      return {
        id: target.id,
        status: target.status,
        revoke_reason: target.revoke_reason,
        revoked_at: target.revoked_at,
        change_seq: target.change_seq
      };
    }

    return apiClient.revokeCredential(id, { note });
  },

  /**
   * GET /admin/logs (Contract 5.3)
   */
  async getAdminLogs({ limit = 100, source = 'all' } = {}) {
    if (isDemoActive()) {
      return [
        {
          id: 48,
          source: 'server',
          event_id: 'srv-7a1b8c2d',
          event_type: 'credential_issued',
          resource_code: 'A',
          request_id: 101,
          actor: 'admin@demo.local',
          occurred_at: '2026-10-14T08:15:40Z',
          note: 'Issued under Rule R1'
        },
        {
          id: 47,
          source: 'device',
          event_id: 'node-01-000184-fa2b10cd',
          event_type: 'pin_verified',
          resource_code: 'B',
          request_id: 91,
          actor: 'node-01',
          occurred_at: '2026-10-14T07:45:12Z',
          note: 'Hardware relay unlocked'
        }
      ].filter((l) => (source === 'all' ? true : l.source === source));
    }

    return apiClient.getAdminLogs({ limit, source });
  },

  /**
   * GET /admin/nodes (Contract 5.3)
   */
  async getAdminNodes() {
    if (isDemoActive()) {
      return [
        {
          id: 1,
          node_code: 'node-01',
          last_sync_at: '2026-10-14T08:15:40Z',
          last_seen_at: '2026-10-14T08:15:40Z',
          status: 'online',
          firmware_version: '0.1.0',
          server_seq: 50
        }
      ];
    }
    return apiClient.getAdminNodes();
  }
};
