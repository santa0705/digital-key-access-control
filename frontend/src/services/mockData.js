/**
 * Mock Data for Digital Key Access Control System
 * Aligned with contracts-v1 (docs/api-contract.md)
 *
 * Rules:
 * - Timestamps are strict ISO-8601 UTC with 'Z'
 * - Secrets & plain PINs are NEVER included or exposed in admin objects
 * - Masked representations use standard placeholder "••••••"
 */

export const INITIAL_RESOURCES = [
  { id: 1, code: 'A', name: 'Locker A', kind: 'physical', is_active: true },
  { id: 2, code: 'B', name: 'Locker B', kind: 'physical', is_active: true },
  { id: 3, code: 'C', name: 'Server Rack C', kind: 'physical', is_active: true },
  { id: 4, code: 'D', name: 'Simulated Locker D', kind: 'simulated', is_active: true }
];

export const INITIAL_ACCESS_REQUESTS = [
  {
    id: 101,
    resource: { id: 1, code: 'A', name: 'Locker A', kind: 'physical' },
    user: { id: 2, full_name: 'Elena Rostova', email: 'elena.rostova@lab.local' },
    start_at: '2026-10-14T09:00:00Z',
    end_at: '2026-10-14T11:00:00Z',
    purpose: 'Retrieve calibrated oscilloscope for radio frequency testing',
    status: 'pending',
    decision_note: null,
    decided_at: null,
    created_at: '2026-10-14T08:15:32Z',
    credential: null
  },
  {
    id: 102,
    resource: { id: 2, code: 'B', name: 'Locker B', kind: 'physical' },
    user: { id: 3, full_name: 'Marcus Vance', email: 'marcus.v@eng.local' },
    start_at: '2026-10-14T10:30:00Z',
    end_at: '2026-10-14T12:30:00Z',
    purpose: 'Access prototype sensor housing assembly and battery packs',
    status: 'pending',
    decision_note: null,
    decided_at: null,
    created_at: '2026-10-14T08:42:10Z',
    credential: null
  },
  {
    id: 103,
    resource: { id: 3, code: 'C', name: 'Server Rack C', kind: 'physical' },
    user: { id: 4, full_name: 'Sarah Connor', email: 's.connor@sec.local' },
    start_at: '2026-10-14T13:00:00Z',
    end_at: '2026-10-14T14:00:00Z',
    purpose: 'Scheduled node-01 edge gateway firmware inspection and flash verification',
    status: 'pending',
    decision_note: null,
    decided_at: null,
    created_at: '2026-10-14T08:50:00Z',
    credential: null
  },
  {
    id: 104,
    resource: { id: 4, code: 'D', name: 'Simulated Locker D', kind: 'simulated' },
    user: { id: 5, full_name: 'Devin Brooks', email: 'devin@demo.local' },
    start_at: '2026-10-14T15:00:00Z',
    end_at: '2026-10-14T16:00:00Z',
    purpose: 'Bench test automated sync edge case with simulated clock jitter',
    status: 'pending',
    decision_note: null,
    decided_at: null,
    created_at: '2026-10-14T09:05:14Z',
    credential: null
  },
  {
    id: 95,
    resource: { id: 1, code: 'A', name: 'Locker A', kind: 'physical' },
    user: { id: 6, full_name: 'Dr. Jane Thornton', email: 'j.thornton@lab.local' },
    start_at: '2026-10-14T08:00:00Z',
    end_at: '2026-10-14T12:00:00Z',
    purpose: 'Emergency sensor diagnostic retrieval',
    status: 'approved',
    decision_note: 'Approved for urgent bench validation',
    decided_at: '2026-10-14T07:55:00Z',
    created_at: '2026-10-14T07:45:10Z',
    credential: {
      id: 71,
      status: 'active',
      valid_from: '2026-10-14T08:00:00Z',
      valid_until: '2026-10-14T12:00:00Z',
      revoke_reason: null
    }
  },
  {
    id: 94,
    resource: { id: 2, code: 'B', name: 'Locker B', kind: 'physical' },
    user: { id: 7, full_name: 'Alex Rivera', email: 'arivera@demo.local' },
    start_at: '2026-10-14T07:00:00Z',
    end_at: '2026-10-14T08:30:00Z',
    purpose: 'Early morning calibration check',
    status: 'rejected',
    decision_note: 'Locker B unavailable due to scheduled lock mechanism alignment test',
    decided_at: '2026-10-14T06:50:11Z',
    created_at: '2026-10-14T06:40:00Z',
    credential: null
  },
  {
    id: 92,
    resource: { id: 1, code: 'A', name: 'Locker A', kind: 'physical' },
    user: { id: 8, full_name: 'Kenji Sato', email: 'ksato@infra.local' },
    start_at: '2026-10-13T14:00:00Z',
    end_at: '2026-10-13T16:00:00Z',
    purpose: 'Deploy edge gateway prototype firmware',
    status: 'revoked',
    decision_note: 'Approved for session',
    decided_at: '2026-10-13T13:50:00Z',
    created_at: '2026-10-13T13:30:00Z',
    credential: {
      id: 68,
      status: 'revoked',
      valid_from: '2026-10-13T14:00:00Z',
      valid_until: '2026-10-13T16:00:00Z',
      revoke_reason: 'admin'
    }
  }
];

export const INITIAL_CREDENTIALS = [
  {
    id: 71,
    request_id: 95,
    resource: { id: 1, code: 'A', name: 'Locker A', kind: 'physical' },
    user: { id: 6, full_name: 'Dr. Jane Thornton', email: 'j.thornton@lab.local' },
    masked_pin: '••••••',
    credential_ref: 'CR-071',
    valid_from: '2026-10-14T08:00:00Z',
    valid_until: '2026-10-14T12:00:00Z',
    status: 'active',
    revoke_reason: null,
    revoked_at: null,
    change_seq: 48,
    created_at: '2026-10-14T07:55:00Z',
    node_sync_state: 'anchored'
  },
  {
    id: 70,
    request_id: 91,
    resource: { id: 2, code: 'B', name: 'Locker B', kind: 'physical' },
    user: { id: 9, full_name: 'Rachel Zane', email: 'rzane@lab.local' },
    masked_pin: '••••••',
    credential_ref: 'CR-070',
    valid_from: '2026-10-14T09:30:00Z',
    valid_until: '2026-10-14T13:30:00Z',
    status: 'active',
    revoke_reason: null,
    revoked_at: null,
    change_seq: 47,
    created_at: '2026-10-14T07:30:00Z',
    node_sync_state: 'anchored'
  },
  {
    id: 69,
    request_id: 88,
    resource: { id: 4, code: 'D', name: 'Simulated Locker D', kind: 'simulated' },
    user: { id: 10, full_name: 'Carlos Mendez', email: 'cmendez@firmware.local' },
    masked_pin: '••••••',
    credential_ref: 'CR-069',
    valid_from: '2026-10-14T06:00:00Z',
    valid_until: '2026-10-14T07:30:00Z',
    status: 'consumed',
    revoke_reason: null,
    revoked_at: null,
    change_seq: 46,
    created_at: '2026-10-14T05:50:00Z',
    node_sync_state: 'anchored'
  },
  {
    id: 68,
    request_id: 92,
    resource: { id: 1, code: 'A', name: 'Locker A', kind: 'physical' },
    user: { id: 8, full_name: 'Kenji Sato', email: 'ksato@infra.local' },
    masked_pin: '••••••',
    credential_ref: 'CR-068',
    valid_from: '2026-10-13T14:00:00Z',
    valid_until: '2026-10-13T16:00:00Z',
    status: 'revoked',
    revoke_reason: 'admin',
    revoked_at: '2026-10-13T14:45:12Z',
    change_seq: 45,
    created_at: '2026-10-13T13:50:00Z',
    node_sync_state: 'anchored'
  },
  {
    id: 65,
    request_id: 80,
    resource: { id: 3, code: 'C', name: 'Server Rack C', kind: 'physical' },
    user: { id: 11, full_name: 'Simon Glass', email: 'sglass@ops.local' },
    masked_pin: '••••••',
    credential_ref: 'CR-065',
    valid_from: '2026-10-12T10:00:00Z',
    valid_until: '2026-10-12T12:00:00Z',
    status: 'expired',
    revoke_reason: null,
    revoked_at: null,
    change_seq: 42,
    created_at: '2026-10-12T09:40:00Z',
    node_sync_state: 'anchored'
  },
  {
    id: 64,
    request_id: 79,
    resource: { id: 1, code: 'A', name: 'Locker A', kind: 'physical' },
    user: { id: 12, full_name: 'Priya Sharma', email: 'psharma@lab.local' },
    masked_pin: '••••••',
    credential_ref: 'CR-064',
    valid_from: '2026-10-12T08:00:00Z',
    valid_until: '2026-10-12T10:00:00Z',
    status: 'revoked',
    revoke_reason: 'superseded',
    revoked_at: '2026-10-12T08:25:00Z',
    change_seq: 41,
    created_at: '2026-10-12T07:50:00Z',
    node_sync_state: 'anchored'
  }
];
