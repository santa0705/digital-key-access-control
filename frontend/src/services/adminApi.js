import { INITIAL_ACCESS_REQUESTS, INITIAL_CREDENTIALS } from './mockData';

const STORAGE_KEY_REQUESTS = 'dk_mock_access_requests';
const STORAGE_KEY_CREDENTIALS = 'dk_mock_credentials';

function loadStored(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (raw) return JSON.parse(raw);
  } catch (err) {
    console.warn('Failed to parse localStorage for', key, err);
  }
  return JSON.parse(JSON.stringify(fallback));
}

function saveStored(key, data) {
  try {
    localStorage.setItem(key, JSON.stringify(data));
  } catch (err) {
    console.warn('Failed to persist to localStorage', err);
  }
}

let accessRequests = loadStored(STORAGE_KEY_REQUESTS, INITIAL_ACCESS_REQUESTS);
let credentials = loadStored(STORAGE_KEY_CREDENTIALS, INITIAL_CREDENTIALS);
let changeSeqCounter = 50;

/**
 * Isolated Admin API Service
 * Can be swapped with fetch(`/admin/...`) calls when backend routes go live.
 */
export const adminApi = {
  /**
   * GET /admin/access-requests?status={pending|approved|rejected|revoked|all}
   */
  async getAccessRequests(statusFilter = 'all') {
    // Simulate brief network latency
    await new Promise((res) => setTimeout(res, 80));
    if (!statusFilter || statusFilter === 'all') {
      return [...accessRequests];
    }
    return accessRequests.filter((r) => r.status === statusFilter);
  },

  /**
   * Find an active credential assigned to a specific resource code/id (Rule R1 check)
   */
  async getActiveCredentialForResource(resourceCode) {
    await new Promise((res) => setTimeout(res, 30));
    return (
      credentials.find(
        (c) => c.resource?.code === resourceCode && c.status === 'active'
      ) || null
    );
  },

  /**
   * POST /admin/access-requests/{id}/approve
   * Enforces Rule R1: One active credential per resource.
   */
  async approveAccessRequest(id, { note = '', replaceExisting = false } = {}) {
    await new Promise((res) => setTimeout(res, 120));
    const target = accessRequests.find((r) => r.id === Number(id));
    if (!target) {
      const err = new Error(`Access request #${id} not found.`);
      err.code = 'not_found';
      throw err;
    }

    if (target.status !== 'pending') {
      const err = new Error(`Request #${id} is already ${target.status}; only pending requests can be approved.`);
      err.code = 'invalid_state';
      throw err;
    }

    // Check Rule R1
    const existingActive = credentials.find(
      (c) => c.resource?.code === target.resource?.code && c.status === 'active'
    );

    if (existingActive && !replaceExisting) {
      const err = new Error(
        `Resource ${target.resource?.code} has active credential #${existingActive.id} (request #${existingActive.request_id}). Revoke it or approve with replace_existing.`
      );
      err.code = 'active_credential_exists';
      err.existingCredential = existingActive;
      throw err;
    }

    const nowIso = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
    changeSeqCounter += 1;

    // If replacement was confirmed, revoke the existing active credential atomically
    if (existingActive && replaceExisting) {
      existingActive.status = 'revoked';
      existingActive.revoke_reason = 'superseded';
      existingActive.revoked_at = nowIso;
      existingActive.change_seq = changeSeqCounter;

      // Also update its parent request to revoked if present
      const parentReq = accessRequests.find((r) => r.id === existingActive.request_id);
      if (parentReq) {
        parentReq.status = 'revoked';
      }
      changeSeqCounter += 1;
    }

    // Generate new credential (masked representation - plain PIN is never created or stored here)
    const newCredId = Math.max(100, ...credentials.map((c) => c.id)) + 1;
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
      change_seq: changeSeqCounter,
      created_at: nowIso,
      node_sync_state: 'anchored'
    };

    credentials = [newCredential, ...credentials];

    // Update the request
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

    saveStored(STORAGE_KEY_REQUESTS, accessRequests);
    saveStored(STORAGE_KEY_CREDENTIALS, credentials);

    return { ...target };
  },

  /**
   * POST /admin/access-requests/{id}/reject
   */
  async rejectAccessRequest(id, { note = '' } = {}) {
    await new Promise((res) => setTimeout(res, 120));
    const target = accessRequests.find((r) => r.id === Number(id));
    if (!target) {
      const err = new Error(`Access request #${id} not found.`);
      err.code = 'not_found';
      throw err;
    }

    if (target.status !== 'pending') {
      const err = new Error(`Request #${id} is already ${target.status}; only pending requests can be rejected.`);
      err.code = 'invalid_state';
      throw err;
    }

    const nowIso = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
    target.status = 'rejected';
    target.decision_note = note.trim() || 'Rejected by administrator';
    target.decided_at = nowIso;

    saveStored(STORAGE_KEY_REQUESTS, accessRequests);
    return { ...target };
  },

  /**
   * GET /admin/credentials?status={all|active|expired|revoked|consumed}
   */
  async getCredentials(statusFilter = 'all') {
    await new Promise((res) => setTimeout(res, 80));
    if (!statusFilter || statusFilter === 'all') {
      return [...credentials];
    }
    return credentials.filter((c) => c.status === statusFilter);
  },

  /**
   * POST /admin/credentials/{id}/revoke
   */
  async revokeCredential(id, { note = '' } = {}) {
    await new Promise((res) => setTimeout(res, 120));
    const target = credentials.find((c) => c.id === Number(id));
    if (!target) {
      const err = new Error(`Credential #${id} not found.`);
      err.code = 'not_found';
      throw err;
    }

    if (target.status !== 'active' && target.status !== 'pending') {
      const err = new Error(`Credential #${id} is already in terminal status "${target.status}".`);
      err.code = 'invalid_state';
      throw err;
    }

    const nowIso = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
    changeSeqCounter += 1;

    target.status = 'revoked';
    target.revoke_reason = 'admin';
    target.revoked_at = nowIso;
    target.admin_revoke_note = note.trim() || 'Admin manual revocation';
    target.change_seq = changeSeqCounter;

    // Update corresponding access request if present
    const parentReq = accessRequests.find((r) => r.id === target.request_id);
    if (parentReq) {
      parentReq.status = 'revoked';
      if (parentReq.credential) {
        parentReq.credential.status = 'revoked';
        parentReq.credential.revoke_reason = 'admin';
      }
    }

    saveStored(STORAGE_KEY_REQUESTS, accessRequests);
    saveStored(STORAGE_KEY_CREDENTIALS, credentials);

    return {
      id: target.id,
      status: target.status,
      revoke_reason: target.revoke_reason,
      revoked_at: target.revoked_at,
      change_seq: target.change_seq
    };
  },

  /**
   * Reset mock data to pristine initial baseline
   */
  resetMockData() {
    accessRequests = JSON.parse(JSON.stringify(INITIAL_ACCESS_REQUESTS));
    credentials = JSON.parse(JSON.stringify(INITIAL_CREDENTIALS));
    saveStored(STORAGE_KEY_REQUESTS, accessRequests);
    saveStored(STORAGE_KEY_CREDENTIALS, credentials);
  }
};
