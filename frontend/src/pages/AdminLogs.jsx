import { useState, useEffect } from 'react';
import { Shield, Terminal, RefreshCw, AlertCircle, Inbox } from 'lucide-react';
import { adminApi } from '../services/adminApi';
import { formatIstDateTime } from '../utils/dateUtils';
import Toast from '../components/Toast';
import Button from '../components/Button';

export default function AdminLogs() {
  const [sourceFilter, setSourceFilter] = useState('all');
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState(null);

  const loadLogs = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await adminApi.getAdminLogs({ limit: 100, source: sourceFilter });
      setLogs(Array.isArray(data) ? data : []);
    } catch (err) {
      const msg = err.code === 'unauthorized'
        ? 'Authentication required. Please sign in as an administrator.'
        : err.code === 'network_error'
        ? `Could not reach backend at ${adminApi.getBaseUrl()}. Please ensure the backend server is running.`
        : err.message || 'Failed to load security audit logs.';
      setError(msg);
      setToast({ type: 'error', message: msg });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadLogs();
  }, [sourceFilter]);

  return (
    <div className="admin-page-container">
      {toast && (
        <Toast
          type={toast.type}
          message={toast.message}
          onClose={() => setToast(null)}
        />
      )}

      <div className="page-header">
        <div>
          <h1 className="page-title">Unified Security Audit Logs</h1>
          <p className="page-description">
            Chronological audit stream combining ESP32 edge terminal events and central server operations (<code>/admin/logs</code>).
          </p>
        </div>
        <Button
          variant="secondary"
          icon={RefreshCw}
          onClick={loadLogs}
          disabled={loading}
          loading={loading}
        >
          Refresh Logs
        </Button>
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

      {error && (
        <div className="alert-box alert-danger" style={{ marginBottom: '16px' }}>
          <AlertCircle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
          <div style={{ flex: 1 }}>{error}</div>
          <Button variant="secondary" size="sm" onClick={loadLogs}>
            Retry
          </Button>
        </div>
      )}

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
              <th>Timestamp (IST)</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={8} style={{ textAlign: 'center', padding: '36px' }}>
                  <div className="btn-spinner" style={{ margin: '0 auto 8px', width: '18px', height: '18px' }} />
                  <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Loading security audit logs...</span>
                </td>
              </tr>
            ) : logs.length === 0 ? (
              <tr>
                <td colSpan={8}>
                  <div className="empty-state">
                    <div className="empty-state-icon">
                      <Inbox size={20} />
                    </div>
                    <div className="empty-state-title">No audit logs found</div>
                    <div className="empty-state-desc">
                      {error ? 'Failed to fetch logs from backend.' : `No ${sourceFilter !== 'all' ? sourceFilter : ''} security events recorded yet.`}
                    </div>
                  </div>
                </td>
              </tr>
            ) : (
              logs.map((log) => (
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
                    <span className="resource-code">{log.resource_code || '—'}</span>
                  </td>
                  <td>
                    <span style={{ fontSize: '12px' }}>{log.actor || '—'}</span>
                  </td>
                  <td>
                    <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                      {formatIstDateTime(log.occurred_at)}
                    </span>
                  </td>
                  <td>
                    <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                      {log.note || '—'}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
