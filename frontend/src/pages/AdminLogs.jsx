import { useState } from 'react';
import { Shield, Terminal } from 'lucide-react';
import { formatUtcDateTime } from '../utils/dateUtils';

const MOCK_AUDIT_LOGS = [
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
  },
  {
    id: 46,
    source: 'server',
    event_id: 'srv-3b91c4ea',
    event_type: 'credential_revoked',
    resource_code: 'A',
    request_id: 92,
    actor: 'admin@demo.local',
    occurred_at: '2026-10-13T14:45:12Z',
    note: 'Admin manual revocation'
  },
  {
    id: 45,
    source: 'device',
    event_id: 'node-01-000183-bc88ef12',
    event_type: 'pin_rejected',
    resource_code: 'A',
    request_id: null,
    actor: 'node-01',
    occurred_at: '2026-10-13T12:04:19Z',
    note: 'Wrong PIN entered (fail counter incremented)'
  }
];

export default function AdminLogs() {
  const [sourceFilter, setSourceFilter] = useState('all');

  const filtered = MOCK_AUDIT_LOGS.filter((l) =>
    sourceFilter === 'all' ? true : l.source === sourceFilter
  );

  return (
    <div className="admin-page-container">
      <div className="page-header">
        <div>
          <h1 className="page-title">Unified Security Audit Logs</h1>
          <p className="page-description">
            Chronological audit stream combining ESP32 edge terminal events and central server operations (<code>/admin/logs</code>).
          </p>
        </div>
      </div>

      <div className="toolbar-bar">
        <div className="filter-tabs">
          <button
            type="button"
            className={`filter-tab-btn ${sourceFilter === 'all' ? 'is-active' : ''}`}
            onClick={() => setSourceFilter('all')}
          >
            All Events
          </button>
          <button
            type="button"
            className={`filter-tab-btn ${sourceFilter === 'server' ? 'is-active' : ''}`}
            onClick={() => setSourceFilter('server')}
          >
            Server Operations
          </button>
          <button
            type="button"
            className={`filter-tab-btn ${sourceFilter === 'device' ? 'is-active' : ''}`}
            onClick={() => setSourceFilter('device')}
          >
            Edge Nodes (ESP32)
          </button>
        </div>
      </div>

      <div className="table-wrapper">
        <table className="admin-table">
          <thead>
            <tr>
              <th style={{ width: '80px' }}>Log ID</th>
              <th>Source</th>
              <th>Event ID</th>
              <th>Event Type</th>
              <th>Resource</th>
              <th>Actor</th>
              <th>Timestamp (UTC)</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((log) => (
              <tr key={log.id}>
                <td>
                  <span className="id-badge">#{log.id}</span>
                </td>
                <td>
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '4px',
                      fontSize: '11px',
                      textTransform: 'uppercase',
                      fontWeight: 600,
                      color: log.source === 'device' ? '#2563eb' : '#059669'
                    }}
                  >
                    {log.source === 'device' ? <Terminal size={12} /> : <Shield size={12} />}
                    {log.source}
                  </span>
                </td>
                <td>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)' }}>
                    {log.event_id}
                  </span>
                </td>
                <td>
                  <span style={{ fontWeight: 600, fontSize: '12px' }}>
                    {log.event_type}
                  </span>
                </td>
                <td>
                  <span className="resource-code">{log.resource_code}</span>
                </td>
                <td>
                  <span style={{ fontSize: '12px' }}>{log.actor}</span>
                </td>
                <td>
                  <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                    {formatUtcDateTime(log.occurred_at)}
                  </span>
                </td>
                <td>
                  <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{log.note}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
