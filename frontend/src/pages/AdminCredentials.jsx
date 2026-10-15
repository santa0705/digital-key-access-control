import { useState, useEffect, useMemo } from 'react';
import {
  Key,
  ShieldAlert,
  ShieldCheck,
  Search,
  AlertTriangle,
  Layers,
  CheckCircle2,
  Info
} from 'lucide-react';
import { adminApi } from '../services/adminApi';
import Badge from '../components/Badge';
import Button from '../components/Button';
import Modal from '../components/Modal';
import StatCard from '../components/StatCard';
import Toast from '../components/Toast';
import { formatTimeRange, formatUtcDateTime, isWindowActive } from '../utils/dateUtils';

export default function AdminCredentials() {
  const [credentials, setCredentials] = useState([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');

  // Revoke Modal State
  const [revokeModal, setRevokeModal] = useState({
    isOpen: false,
    credential: null,
    note: '',
    isSubmitting: false,
    errorMessage: ''
  });

  // Detail Modal State
  const [detailModal, setDetailModal] = useState({
    isOpen: false,
    credential: null
  });

  // Toast feedback
  const [toast, setToast] = useState(null);

  // Load credentials
  const loadCredentials = async () => {
    setLoading(true);
    try {
      const data = await adminApi.getCredentials('all');
      setCredentials(data);
    } catch (err) {
      setToast({ type: 'error', message: `Failed to load credentials: ${err.message}` });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCredentials();
  }, []);

  // Filter credentials
  const filteredCredentials = useMemo(() => {
    return credentials.filter((c) => {
      if (statusFilter !== 'all' && c.status !== statusFilter) {
        return false;
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesUser = c.user?.full_name?.toLowerCase().includes(q) || c.user?.email?.toLowerCase().includes(q);
        const matchesResource = c.resource?.name?.toLowerCase().includes(q) || c.resource?.code?.toLowerCase().includes(q);
        const matchesRef = c.credential_ref?.toLowerCase().includes(q) || String(c.id).includes(q);
        return matchesUser || matchesResource || matchesRef;
      }
      return true;
    });
  }, [credentials, statusFilter, searchQuery]);

  // Stats
  const stats = useMemo(() => {
    const total = credentials.length;
    const active = credentials.filter((c) => c.status === 'active').length;
    const consumed = credentials.filter((c) => c.status === 'consumed').length;
    const expired = credentials.filter((c) => c.status === 'expired').length;
    const revoked = credentials.filter((c) => c.status === 'revoked').length;
    return { total, active, consumed, expired, revoked };
  }, [credentials]);

  // Open Revoke Modal
  const handleOpenRevoke = (cred) => {
    setRevokeModal({
      isOpen: true,
      credential: cred,
      note: 'Key reported compromised / security recall',
      isSubmitting: false,
      errorMessage: ''
    });
  };

  // Submit Revocation
  const handleConfirmRevoke = async () => {
    const { credential, note } = revokeModal;
    if (!credential) return;

    setRevokeModal((prev) => ({ ...prev, isSubmitting: true, errorMessage: '' }));

    try {
      const result = await adminApi.revokeCredential(credential.id, { note });

      // Update local state directly
      setCredentials((prev) =>
        prev.map((c) =>
          c.id === credential.id
            ? {
                ...c,
                status: 'revoked',
                revoke_reason: 'admin',
                revoked_at: result.revoked_at,
                change_seq: result.change_seq,
                admin_revoke_note: note
              }
            : c
        )
      );

      setToast({
        type: 'success',
        message: `Credential #${credential.id} (${credential.credential_ref || 'CR'}) revoked. Monotonic sync seq advanced to ${result.change_seq}.`
      });

      setRevokeModal({
        isOpen: false,
        credential: null,
        note: '',
        isSubmitting: false,
        errorMessage: ''
      });
    } catch (err) {
      setRevokeModal((prev) => ({
        ...prev,
        isSubmitting: false,
        errorMessage: err.message || 'Failed to revoke credential'
      }));
    }
  };

  return (
    <div className="admin-page-container">
      {/* Toast */}
      {toast && (
        <Toast
          type={toast.type}
          message={toast.message}
          onClose={() => setToast(null)}
        />
      )}

      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Digital Credentials & Key Invalidation</h1>
          <p className="page-description">
            Monitor issued unlock credentials, enforce Rule R1 single-occupancy locks, and execute instant key revocations.
          </p>
        </div>
      </div>

      {/* KPI Stats */}
      <div className="stats-grid">
        <StatCard
          label="Active Keys"
          value={stats.active}
          subtext="Valid physical unlock credentials"
          icon={ShieldCheck}
          tone="approved"
          active={statusFilter === 'active'}
          onClick={() => setStatusFilter('active')}
        />
        <StatCard
          label="Consumed"
          value={stats.consumed}
          subtext="Used for terminal entry"
          icon={CheckCircle2}
          active={statusFilter === 'consumed'}
          onClick={() => setStatusFilter('consumed')}
        />
        <StatCard
          label="Revoked Keys"
          value={stats.revoked}
          subtext="Superseded or manual recall"
          icon={ShieldAlert}
          tone="pending"
          active={statusFilter === 'revoked'}
          onClick={() => setStatusFilter('revoked')}
        />
        <StatCard
          label="Total Issued"
          value={stats.total}
          subtext="Monotonic counter driven"
          icon={Layers}
          active={statusFilter === 'all'}
          onClick={() => setStatusFilter('all')}
        />
      </div>

      {/* Toolbar */}
      <div className="toolbar-bar">
        <div className="filter-tabs">
          <button
            type="button"
            className={`filter-tab-btn ${statusFilter === 'all' ? 'is-active' : ''}`}
            onClick={() => setStatusFilter('all')}
          >
            All Keys
            <span className="filter-badge-count">{stats.total}</span>
          </button>
          <button
            type="button"
            className={`filter-tab-btn ${statusFilter === 'active' ? 'is-active' : ''}`}
            onClick={() => setStatusFilter('active')}
          >
            Active
            <span className="filter-badge-count">{stats.active}</span>
          </button>
          <button
            type="button"
            className={`filter-tab-btn ${statusFilter === 'consumed' ? 'is-active' : ''}`}
            onClick={() => setStatusFilter('consumed')}
          >
            Consumed
            <span className="filter-badge-count">{stats.consumed}</span>
          </button>
          <button
            type="button"
            className={`filter-tab-btn ${statusFilter === 'revoked' ? 'is-active' : ''}`}
            onClick={() => setStatusFilter('revoked')}
          >
            Revoked
            <span className="filter-badge-count">{stats.revoked}</span>
          </button>
          <button
            type="button"
            className={`filter-tab-btn ${statusFilter === 'expired' ? 'is-active' : ''}`}
            onClick={() => setStatusFilter('expired')}
          >
            Expired
            <span className="filter-badge-count">{stats.expired}</span>
          </button>
        </div>

        <div className="search-input-wrap">
          <Search size={14} className="search-icon" />
          <input
            type="text"
            className="search-input"
            placeholder="Search by key ref, resource or owner..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button
              type="button"
              className="btn-ghost"
              onClick={() => setSearchQuery('')}
              style={{ padding: '0 4px', fontSize: '11px' }}
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="table-wrapper">
        <table className="admin-table">
          <thead>
            <tr>
              <th style={{ width: '90px' }}>Key Ref</th>
              <th>Resource</th>
              <th>Owner / Requester</th>
              <th>PIN Secret</th>
              <th>Validity Window (UTC)</th>
              <th style={{ width: '100px' }}>Status</th>
              <th style={{ width: '110px' }}>Sync Seq</th>
              <th style={{ textAlign: 'right', width: '130px' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={8} style={{ textAlign: 'center', padding: '36px' }}>
                  <div className="btn-spinner" style={{ margin: '0 auto 8px', width: '18px', height: '18px' }} />
                  <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Loading credentials...</span>
                </td>
              </tr>
            ) : filteredCredentials.length === 0 ? (
              <tr>
                <td colSpan={8}>
                  <div className="empty-state">
                    <div className="empty-state-icon">
                      <Key size={20} />
                    </div>
                    <div className="empty-state-title">No credentials found</div>
                    <div className="empty-state-desc">
                      No records matching filter &quot;{statusFilter}&quot; and query &quot;{searchQuery}&quot;.
                    </div>
                    {(statusFilter !== 'all' || searchQuery) && (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => {
                          setStatusFilter('all');
                          setSearchQuery('');
                        }}
                      >
                        Reset filters
                      </Button>
                    )}
                  </div>
                </td>
              </tr>
            ) : (
              filteredCredentials.map((cred) => {
                const isActive = cred.status === 'active';
                const isCurrent = isWindowActive(cred.valid_from, cred.valid_until);

                return (
                  <tr key={cred.id}>
                    <td>
                      <span className="id-badge">
                        {cred.credential_ref || `CR-${String(cred.id).padStart(3, '0')}`}
                      </span>
                    </td>
                    <td>
                      <div className="resource-pill">
                        <span className="resource-code">{cred.resource?.code}</span>
                        <div>
                          <div className="resource-name">{cred.resource?.name}</div>
                          <span className="resource-kind">{cred.resource?.kind}</span>
                        </div>
                      </div>
                    </td>
                    <td>
                      <div className="user-cell">
                        <span className="user-cell-name">{cred.user?.full_name}</span>
                        <span className="user-cell-email">{cred.user?.email}</span>
                      </div>
                    </td>
                    <td>
                      <div className="masked-pin-cell" title="Plaintext PINs are never stored or displayed to admins (C4 & Security Policy)">
                        <span className="masked-pin-text">{cred.masked_pin || '••••••'}</span>
                        <span className="masked-pin-hint">HMAC-SHA256</span>
                      </div>
                    </td>
                    <td>
                      <div className="time-cell">
                        <span className="time-window">
                          {formatTimeRange(cred.valid_from, cred.valid_until)}
                        </span>
                        {isActive && (
                          <span className="time-meta" style={{ color: isCurrent ? 'var(--accent-green-text)' : 'var(--text-muted)' }}>
                            {isCurrent ? '● Active now' : 'Upcoming window'}
                          </span>
                        )}
                        {cred.revoked_at && (
                          <span className="time-meta" style={{ color: 'var(--danger-text)' }}>
                            Revoked: {formatUtcDateTime(cred.revoked_at)}
                            {cred.revoke_reason && ` (${cred.revoke_reason})`}
                          </span>
                        )}
                      </div>
                    </td>
                    <td>
                      <Badge status={cred.status} />
                    </td>
                    <td>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)' }}>
                        seq: {cred.change_seq || '—'}
                      </span>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <div className="table-actions" style={{ justifyContent: 'flex-end' }}>
                        {isActive ? (
                          <Button
                            size="sm"
                            variant="danger"
                            icon={ShieldAlert}
                            onClick={() => handleOpenRevoke(cred)}
                            title="Revoke active key"
                          >
                            Revoke
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="secondary"
                            icon={Info}
                            onClick={() => setDetailModal({ isOpen: true, credential: cred })}
                          >
                            Details
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Revoke Confirmation Modal */}
      <Modal
        isOpen={revokeModal.isOpen}
        onClose={() => setRevokeModal((prev) => ({ ...prev, isOpen: false }))}
        title="Revoke Digital Credential"
        subtitle={`Revoke ${revokeModal.credential?.credential_ref || `CR-${revokeModal.credential?.id}`} — Resource ${revokeModal.credential?.resource?.code}`}
        icon={AlertTriangle}
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setRevokeModal((prev) => ({ ...prev, isOpen: false }))}
              disabled={revokeModal.isSubmitting}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              className="btn-danger-solid"
              onClick={handleConfirmRevoke}
              loading={revokeModal.isSubmitting}
              icon={ShieldAlert}
            >
              Confirm Key Revocation
            </Button>
          </>
        }
      >
        {revokeModal.credential && (
          <>
            <div className="alert-box alert-danger">
              <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: '2px' }} />
              <div>
                <strong>Immediate Invalidation Warning</strong>
                <p style={{ marginTop: '2px' }}>
                  Revoking this credential takes effect on physical edge nodes at the next sync tick (max 90 seconds).
                  The server monotonic counter <code>change_seq</code> will increment.
                </p>
              </div>
            </div>

            <div className="modal-summary-box">
              <div className="summary-row">
                <span className="summary-key">Resource:</span>
                <span className="summary-val">{revokeModal.credential.resource?.name} [{revokeModal.credential.resource?.code}]</span>
              </div>
              <div className="summary-row">
                <span className="summary-key">Assigned To:</span>
                <span className="summary-val">{revokeModal.credential.user?.full_name}</span>
              </div>
              <div className="summary-row">
                <span className="summary-key">Validity Window:</span>
                <span className="summary-val" style={{ fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                  {formatTimeRange(revokeModal.credential.valid_from, revokeModal.credential.valid_until)}
                </span>
              </div>
              <div className="summary-row">
                <span className="summary-key">Current Sequence:</span>
                <span className="summary-val" style={{ fontFamily: 'var(--font-mono)' }}>
                  seq: {revokeModal.credential.change_seq}
                </span>
              </div>
            </div>

            <div className="modal-field">
              <label htmlFor="revoke-reason" className="field-label">
                Revocation Audit Note:
              </label>
              <input
                id="revoke-reason"
                type="text"
                className="field-input"
                placeholder="Reason for revoking key (e.g. Lost token, compromised)"
                value={revokeModal.note}
                onChange={(e) =>
                  setRevokeModal((prev) => ({ ...prev, note: e.target.value }))
                }
              />
            </div>

            {revokeModal.errorMessage && (
              <div className="alert-box alert-danger">
                <AlertTriangle size={16} style={{ flexShrink: 0 }} />
                <span>{revokeModal.errorMessage}</span>
              </div>
            )}
          </>
        )}
      </Modal>

      {/* Detail Modal */}
      <Modal
        isOpen={detailModal.isOpen}
        onClose={() => setDetailModal({ isOpen: false, credential: null })}
        title={`Credential ${detailModal.credential?.credential_ref || `CR-${detailModal.credential?.id}`}`}
        subtitle={`Status: ${detailModal.credential?.status?.toUpperCase()}`}
        icon={Key}
        footer={
          <Button
            variant="secondary"
            onClick={() => setDetailModal({ isOpen: false, credential: null })}
          >
            Close
          </Button>
        }
      >
        {detailModal.credential && (
          <div className="modal-summary-box">
            <div className="summary-row">
              <span className="summary-key">Status:</span>
              <span className="summary-val">
                <Badge status={detailModal.credential.status} />
              </span>
            </div>
            <div className="summary-row">
              <span className="summary-key">Resource:</span>
              <span className="summary-val">{detailModal.credential.resource?.name} ({detailModal.credential.resource?.code})</span>
            </div>
            <div className="summary-row">
              <span className="summary-key">Requester:</span>
              <span className="summary-val">{detailModal.credential.user?.full_name}</span>
            </div>
            <div className="summary-row">
              <span className="summary-key">PIN Security:</span>
              <span className="summary-val" style={{ fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                Keyed HMAC-SHA256 (Never displayed to admins)
              </span>
            </div>
            <div className="summary-row">
              <span className="summary-key">Validity Window:</span>
              <span className="summary-val" style={{ fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                {formatTimeRange(detailModal.credential.valid_from, detailModal.credential.valid_until)}
              </span>
            </div>
            <div className="summary-row">
              <span className="summary-key">Change Sequence:</span>
              <span className="summary-val" style={{ fontFamily: 'var(--font-mono)' }}>
                seq: {detailModal.credential.change_seq}
              </span>
            </div>
            {detailModal.credential.revoke_reason && (
              <div className="summary-row">
                <span className="summary-key">Revoke Reason:</span>
                <span className="summary-val" style={{ color: 'var(--danger-text)' }}>
                  {detailModal.credential.revoke_reason} ({detailModal.credential.admin_revoke_note || 'Manual action'})
                </span>
              </div>
            )}
            {detailModal.credential.revoked_at && (
              <div className="summary-row">
                <span className="summary-key">Revoked At:</span>
                <span className="summary-val" style={{ fontSize: '11px' }}>
                  {formatUtcDateTime(detailModal.credential.revoked_at)}
                </span>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
