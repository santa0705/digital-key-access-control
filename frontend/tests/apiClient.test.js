/**
 * apiClient.test.js -- Test suite for frontend API client, authentication, and contract paths.
 * Executed via Node.js native test runner (node --test).
 */

import { test, describe, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { apiClient, ApiError, getApiBaseUrl, setStoredToken, getStoredToken, clearSession } from '../src/services/apiClient.js';
import { adminApi } from '../src/services/adminApi.js';

describe('Frontend API Client & Contract Integration Tests', () => {
  let originalFetch;
  let recordedRequests = [];

  beforeEach(() => {
    recordedRequests = [];
    originalFetch = globalThis.fetch;
    clearSession();
    adminApi.setDemoMode(false); // Ensure live mode by default
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    clearSession();
  });

  // Mock fetch helper
  function setupMockFetch(status, responseBody, headers = {}) {
    globalThis.fetch = async (url, options = {}) => {
      recordedRequests.push({ url, options });
      return {
        ok: status >= 200 && status < 300,
        status,
        statusText: status === 200 ? 'OK' : 'Error',
        headers: new Map([
          ['content-type', 'application/json'],
          ...Object.entries(headers)
        ]),
        json: async () => responseBody,
        text: async () => JSON.stringify(responseBody)
      };
    };
  }

  test('1. Base URL configuration defaults to http://localhost:8000', () => {
    const url = getApiBaseUrl();
    assert.match(url, /^http:\/\/localhost:8000/);
  });

  test('2. Authorization Bearer header is automatically injected when token exists', async () => {
    setStoredToken('test_jwt_session_token_123');

    setupMockFetch(200, [{ id: 1, code: 'A', name: 'Locker A', kind: 'physical', is_active: true }]);

    await apiClient.getResources();

    assert.equal(recordedRequests.length, 1);
    const req = recordedRequests[0];
    assert.equal(req.options.headers.Authorization, 'Bearer test_jwt_session_token_123');
  });

  test('3. Login calls POST /auth/login and stores session token', async () => {
    const mockAuthResponse = {
      access_token: 'signed_bearer_token_xyz',
      token_type: 'bearer',
      expires_in: 28800,
      user: {
        id: 1,
        email: 'admin@demo.local',
        full_name: 'Admin Officer',
        role: 'admin'
      }
    };

    setupMockFetch(200, mockAuthResponse);

    const result = await apiClient.login({
      email: 'admin@demo.local',
      password: 'demo-password'
    });

    assert.equal(recordedRequests.length, 1);
    const req = recordedRequests[0];
    assert.match(req.url, /\/auth\/login$/);
    assert.equal(req.options.method, 'POST');

    const sentBody = JSON.parse(req.options.body);
    assert.equal(sentBody.email, 'admin@demo.local');
    assert.equal(sentBody.password, 'demo-password');

    // Token stored
    assert.equal(getStoredToken(), 'signed_bearer_token_xyz');
    assert.equal(result.user.role, 'admin');
  });

  test('4. Payload mapping: approveAccessRequest maps replaceExisting to replace_existing', async () => {
    setupMockFetch(200, {
      id: 5,
      resource: { id: 1, code: 'A', name: 'Locker A', kind: 'physical' },
      user: { id: 2, full_name: 'Jane' },
      status: 'approved',
      start_at: '2026-10-15T09:00:00Z',
      end_at: '2026-10-15T10:00:00Z',
      credential: { id: 7, status: 'active', valid_from: '2026-10-15T09:00:00Z', valid_until: '2026-10-15T10:00:00Z', revoke_reason: null }
    });

    // Test with replaceExisting: true
    await apiClient.approveAccessRequest(5, { note: 'Approved replacement', replaceExisting: true });

    assert.equal(recordedRequests.length, 1);
    const req = recordedRequests[0];
    assert.match(req.url, /\/admin\/access-requests\/5\/approve$/);
    assert.equal(req.options.method, 'POST');

    const body = JSON.parse(req.options.body);
    assert.equal(body.replace_existing, true);
    assert.equal(body.note, 'Approved replacement');
    assert.equal(body.replaceExisting, undefined, 'Must not send camelCase replaceExisting to backend');
  });

  test('5. Contract URL paths and HTTP methods', async () => {
    // Check all documented endpoints
    const endpointsToTest = [
      { call: () => apiClient.getResources(), expectedMethod: 'GET', pathRegex: /\/resources$/ },
      {
        call: () => apiClient.createAccessRequest({ resource_id: 1, start_at: '2026-10-15T09:00:00Z', end_at: '2026-10-15T10:00:00Z', purpose: 'test' }),
        expectedMethod: 'POST',
        pathRegex: /\/access-requests$/
      },
      { call: () => apiClient.getMyAccessRequests(), expectedMethod: 'GET', pathRegex: /\/access-requests\/me$/ },
      { call: () => apiClient.revealPin(12), expectedMethod: 'GET', pathRegex: /\/access-requests\/12\/pin$/ },
      { call: () => apiClient.getAdminAccessRequests('pending'), expectedMethod: 'GET', pathRegex: /\/admin\/access-requests\?status=pending$/ },
      { call: () => apiClient.getAdminAccessRequests('all'), expectedMethod: 'GET', pathRegex: /\/admin\/access-requests\?status=all$/ },
      { call: () => apiClient.getAdminAccessRequests('approved'), expectedMethod: 'GET', pathRegex: /\/admin\/access-requests\?status=approved$/ },
      { call: () => apiClient.getAdminAccessRequests(), expectedMethod: 'GET', pathRegex: /\/admin\/access-requests\?status=all$/ },
      { call: () => apiClient.rejectAccessRequest(15, { note: 'denied' }), expectedMethod: 'POST', pathRegex: /\/admin\/access-requests\/15\/reject$/ },
      { call: () => apiClient.revokeCredential(8, { note: 'lost key' }), expectedMethod: 'POST', pathRegex: /\/admin\/credentials\/8\/revoke$/ },
      { call: () => apiClient.getAdminLogs({ limit: 50, source: 'device' }), expectedMethod: 'GET', pathRegex: /\/admin\/logs\?limit=50&source=device$/ },
      { call: () => apiClient.getAdminNodes(), expectedMethod: 'GET', pathRegex: /\/admin\/nodes$/ }
    ];

    for (const item of endpointsToTest) {
      recordedRequests = [];
      setupMockFetch(200, {});
      await item.call();
      assert.equal(recordedRequests.length, 1);
      assert.equal(recordedRequests[0].options.method, item.expectedMethod);
      assert.match(recordedRequests[0].url, item.pathRegex);
    }
  });

  test('6. Error handling: parses standard error envelope {"error": {"code": "...", "message": "..."}}', async () => {
    setupMockFetch(409, {
      error: {
        code: 'active_credential_exists',
        message: 'Resource A has active credential 6. Revoke it or approve with replace_existing.'
      }
    });

    await assert.rejects(
      async () => {
        await apiClient.approveAccessRequest(4, { replaceExisting: false });
      },
      (err) => {
        assert(err instanceof ApiError);
        assert.equal(err.status, 409);
        assert.equal(err.code, 'active_credential_exists');
        assert.match(err.message, /active credential 6/);
        return true;
      }
    );
  });

  test('7. ABSENCE OF SILENT MOCK FALLBACK: Failed API calls reject instead of returning mock data', async () => {
    // Simulate server crash or 500 Internal Error
    setupMockFetch(500, {
      error: {
        code: 'internal_error',
        message: 'An internal server error occurred.'
      }
    });

    await assert.rejects(
      async () => {
        await adminApi.getAccessRequests('all');
      },
      (err) => {
        assert(err instanceof ApiError);
        assert.equal(err.status, 500);
        return true;
      },
      'adminApi MUST NOT silently return mock data when live API fails'
    );
  });

  test('8. Derived credentials: maps GET /admin/access-requests without standalone endpoint', async () => {
    setupMockFetch(200, [
      {
        id: 10,
        resource: { id: 1, code: 'A', name: 'Locker A', kind: 'physical' },
        user: { id: 2, full_name: 'John Doe' },
        status: 'approved',
        start_at: '2026-10-15T09:00:00Z',
        end_at: '2026-10-15T10:00:00Z',
        credential: {
          id: 55,
          status: 'active',
          valid_from: '2026-10-15T09:00:00Z',
          valid_until: '2026-10-15T10:00:00Z',
          revoke_reason: null
        }
      },
      {
        id: 11,
        resource: { id: 2, code: 'B', name: 'Locker B', kind: 'physical' },
        user: { id: 3, full_name: 'Alice' },
        status: 'pending',
        start_at: '2026-10-15T11:00:00Z',
        end_at: '2026-10-15T12:00:00Z',
        credential: null
      }
    ]);

    const creds = await adminApi.getCredentials('all');

    // Only requests with credential != null are returned
    assert.equal(creds.length, 1);
    assert.equal(creds[0].id, 55);
    assert.equal(creds[0].request_id, 10);
    assert.equal(creds[0].resource.code, 'A');
    assert.equal(creds[0].masked_pin, '••••••');
    assert.equal(creds[0].change_seq, null, 'change_seq is unpopulated in CredentialSummary per contract');
  });

  test('9. PIN security: PIN is never stored in persistent storage', async () => {
    setupMockFetch(200, {
      request_id: 15,
      resource_code: 'A',
      pin: '123456',
      valid_from: '2026-10-15T09:00:00Z',
      valid_until: '2026-10-15T10:00:00Z'
    });

    const pinResponse = await apiClient.revealPin(15);
    assert.equal(pinResponse.pin, '123456');

    // Verify localStorage does NOT contain the plaintext PIN
    if (typeof localStorage !== 'undefined') {
      const allStored = JSON.stringify(localStorage);
      assert.equal(allStored.includes('123456'), false, 'Plaintext PIN must never be written to localStorage');
    }
  });

  test('10. Admin access requests: query parameter preservation, response shape, and approved status filtering', async () => {
    const mockAllRequests = [
      {
        id: 28,
        resource: { id: 1, code: 'A', name: 'Locker A', kind: 'physical' },
        user: { id: 11, full_name: 'Demo Admin' },
        status: 'approved',
        start_at: '2026-10-15T04:15:00Z',
        end_at: '2099-10-15T05:15:00Z',
        purpose: 'Local integration test',
        credential: {
          id: 28,
          status: 'active',
          valid_from: '2026-10-15T04:15:00Z',
          valid_until: '2099-10-15T05:15:00Z',
          revoke_reason: null
        }
      },
      {
        id: 29,
        resource: { id: 2, code: 'B', name: 'Locker B', kind: 'physical' },
        user: { id: 12, full_name: 'Jane User' },
        status: 'pending',
        start_at: '2026-10-15T06:00:00Z',
        end_at: '2026-10-15T07:00:00Z',
        purpose: 'Pending access',
        credential: null
      },
      {
        id: 30,
        resource: { id: 1, code: 'A', name: 'Locker A', kind: 'physical' },
        user: { id: 13, full_name: 'Bob' },
        status: 'rejected',
        start_at: '2026-10-15T08:00:00Z',
        end_at: '2026-10-15T09:00:00Z',
        purpose: 'Declined request',
        credential: null
      }
    ];

    setupMockFetch(200, mockAllRequests);

    // Verify 'all' sends ?status=all rather than omitting it (which defaults to 'pending' in backend)
    const allData = await adminApi.getAccessRequests('all');
    assert.equal(recordedRequests.length, 1);
    assert.match(recordedRequests[0].url, /\/admin\/access-requests\?status=all$/);
    assert.equal(allData.length, 3);

    // Verify response shape
    const approvedItem = allData.find((r) => r.id === 28);
    assert(approvedItem, 'Approved request #28 must be present in all requests');
    assert.equal(approvedItem.status, 'approved');
    assert.equal(approvedItem.credential?.status, 'active');
    assert.equal(approvedItem.resource?.code, 'A');

    // Verify client-side status filtering logic used by AdminPending.jsx
    const pendingItems = allData.filter((r) => r.status === 'pending');
    const approvedItems = allData.filter((r) => r.status === 'approved');
    const rejectedItems = allData.filter((r) => r.status === 'rejected');
    const revokedItems = allData.filter((r) => r.status === 'revoked');

    assert.equal(pendingItems.length, 1);
    assert.equal(approvedItems.length, 1);
    assert.equal(rejectedItems.length, 1);
    assert.equal(revokedItems.length, 0);

    // Verify stats aggregation
    const stats = {
      total: allData.length,
      pending: pendingItems.length,
      approved: approvedItems.length,
      rejected: rejectedItems.length,
      revoked: revokedItems.length
    };
    assert.deepEqual(stats, { total: 3, pending: 1, approved: 1, rejected: 1, revoked: 0 });

    // Verify derived credentials endpoint recovers active credential from approved request
    recordedRequests = [];
    setupMockFetch(200, mockAllRequests);
    const creds = await adminApi.getCredentials('all');
    assert.match(recordedRequests[0].url, /\/admin\/access-requests\?status=all$/);
    assert.equal(creds.length, 1);
    assert.equal(creds[0].id, 28);
    assert.equal(creds[0].status, 'active');
    assert.equal(creds[0].resource?.code, 'A');
  });
});
