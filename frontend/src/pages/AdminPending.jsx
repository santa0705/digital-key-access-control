import { useState, useEffect, useMemo } from 'react';
import {
  Clock,
  Check,
  X,
  AlertTriangle,
  Search,
  CheckCircle2,
  XCircle,
  FileText,
  Shield,
  Layers,
  Info
} from 'lucide-react';
import { adminApi } from '../services/adminApi';
import Badge from '../components/Badge';
import Button from '../components/Button';
import Modal from '../components/Modal';
import StatCard from '../components/StatCard';
import Toast from '../components/Toast';
import { formatTimeRange, formatIstDateTime, calculateDuration } from '../utils/dateUtils';

export default function AdminPending() {
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('pending');
  const [searchQuery, setSearchQuery] = useState('');

  // Modals state
  const [approveModal, setApproveModal] = useState({
    isOpen: false,
    request: null,
    note: '',
    replaceExisting: false,
    activeCredentialConflict: null,
    isSubmitting: false,
    errorMessage: ''
  });

  const [rejectModal, setRejectModal] = useState({
    isOpen: false,
    request: null,
    note: '',
    isSubmitting: false,
    errorMessage: ''
  });

  const [detailModal, setDetailModal] = useState({
    isOpen: false,
    request: null
  });

  // Toast feedback
  const [toast, setToast] = useState(null);

  // Load data
  const loadRequests = async () => {
    setLoading(true);
    try {
      const data = await adminApi.getAccessRequests('all');
      setRequests(Array.isArray(data) ? data : []);
    } catch (err) {
      const msg = err.code === 'unauthorized'
        ? 'Authentication required. Please sign in as an administrator.'
        : err.code === 'network_error'
        ? `Could not reach backend at ${adminApi.getBaseUrl()}. Please ensure the backend is running.`
        : `Failed to load requests: ${err.message}`;
      setToast({ type: 'error', message: msg });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadRequests();
  }, []);

  // Filtered requests
  const filteredRequests = useMemo(() => {
    return requests.filter((r) => {
      // Status filter
      if (statusFilter !== 'all' && r.status !== statusFilter) {
        return false;
      }
      // Search filter
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesUser = r.user?.full_name?.toLowerCase().includes(q) || r.user?.email?.toLowerCase().includes(q);
        const matchesResource = r.resource?.name?.toLowerCase().includes(q) || r.resource?.code?.toLowerCase().includes(q);
        const matchesPurpose = r.purpose?.toLowerCase().includes(q);
        const matchesId = String(r.id).includes(q);
        return matchesUser || matchesResource || matchesPurpose || matchesId;
      }
      return true;
    });
  }, [requests, statusFilter, searchQuery]);

  // Aggregate stats
  const stats = useMemo(() => {
    const total = requests.length;
    const pending = requests.filter((r) => r.status === 'pending').length;
    const approved = requests.filter((r) => r.status === 'approved').length;
    const rejected = requests.filter((r) => r.status === 'rejected').length;
    const revoked = requests.filter((r) => r.status === 'revoked').length;
    return { total, pending, approved, rejected, revoked };
  }, [requests]);

  // Handle open Approve Modal
  const handleOpenApprove = async (req) => {
    setApproveModal({
      isOpen: true,
      request: req,
      note: 'Approved for session',
      replaceExisting: false,
      activeCredentialConflict: null,
      isSubmitting: false,
      errorMessage: ''
    });

    // Check Rule R1: Active credential conflict check
    try {
      const existing = await adminApi.getActiveCredentialForResource(req.resource?.code);
      if (existing) {
        setApproveModal((prev) => ({
          ...prev,
          activeCredentialConflict: existing
        }));
      }
    } catch (err) {
      console.warn('Error checking resource credential', err);
    }
  };

  // Submit Approval
  const handleConfirmApprove = async () => {
    const { request, note, replaceExisting, activeCredentialConflict } = approveModal;
    if (!request) return;

    if (activeCredentialConflict && !replaceExisting) {
      setApproveModal((prev) => ({
        ...prev,
        errorMessage: 'Rule R1 requires explicit replacement consent before replacing an active key.'
      }));
      return;
    }

    setApproveModal((prev) => ({ ...prev, isSubmitting: true, errorMessage: '' }));

    try {
      const updated = await adminApi.approveAccessRequest(request.id, {
        note,
        replaceExisting
      });

      // Update local state directly
      setRequests((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item))
      );

      setToast({
        type: 'success',
        message: `Request #${request.id} for ${request.user?.full_name} approved. Active credential issued.`
      });

      setApproveModal({
        isOpen: false,
        request: null,
        note: '',
        replaceExisting: false,
        activeCredentialConflict: null,
        isSubmitting: false,
        errorMessage: ''
      });

      // Refresh to capture any superseded requests
      loadRequests();
    } catch (err) {
      if (err.code === 'active_credential_exists') {
        setApproveModal((prev) => ({
          ...prev,
          isSubmitting: false,
          activeCredentialConflict: prev.activeCredentialConflict || { resource: request.resource },
          errorMessage: 'An active credential already exists for this resource. Check "Replace existing credential" to supersede it.'
        }));
      } else {
        setApproveModal((prev) => ({
          ...prev,
          isSubmitting: false,
          errorMessage: err.message || 'Failed to approve request'
        }));
      }
    }
  };

  // Handle open Reject Modal
  const handleOpenReject = (req) => {
    setRejectModal({
      isOpen: true,
      request: req,
      note: 'Resource unavailable due to maintenance',
      isSubmitting: false,
      errorMessage: ''
    });
  };

  // Submit Rejection
  const handleConfirmReject = async () => {
    const { request, note } = rejectModal;
    if (!request) return;

    setRejectModal((prev) => ({ ...prev, isSubmitting: true, errorMessage: '' }));

    try {
      const updated = await adminApi.rejectAccessRequest(request.id, { note });

      setRequests((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item))
      );

      setToast({
        type: 'success',
        message: `Request #${request.id} for ${request.user?.full_name} rejected.`
      });

      setRejectModal({
        isOpen: false,
        request: null,
        note: '',
        isSubmitting: false,
        errorMessage: ''
      });
    } catch (err) {
      setRejectModal((prev) => ({
        ...prev,
        isSubmitting: false,
        errorMessage: err.message || 'Failed to reject request'
      }));
    }
  };

  return (
    <div className="admin-page-container">
      {/* Toast Feedback */}
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
          <h1 className="page-title">Access Request Approvals</h1>
          <p className="page-description">
            Review incoming physical and simulated locker access requests. Authorize single-credential issuance per Rule R1.
          </p>
        </div>
      </div>

      {/* KPI Stat Cards */}
      <div className="stats-grid">
        <StatCard
          label="Pending Review"
          value={stats.pending}
          subtext="Requires administrator action"
          icon={Clock}
          tone="pending"
          active={statusFilter === 'pending'}
          onClick={() => setStatusFilter('pending')}
        />
        <StatCard
          label="Approved Requests"
          value={stats.approved}
          subtext="Credentials issued"
          icon={CheckCircle2}
          tone="approved"
          active={statusFilter === 'approved'}
          onClick={() => setStatusFilter('approved')}
        />
        <StatCard
          label="Rejected"
          value={stats.rejected}
          subtext="Access declined"
          icon={XCircle}
          active={statusFilter === 'rejected'}
          onClick={() => setStatusFilter('rejected')}
        />
        <StatCard
          label="Total All-Time"
          value={stats.total}
          subtext="Contract endpoint: /admin/access-requests"
          icon={Layers}
          active={statusFilter === 'all'}
          onClick={() => setStatusFilter('all')}
        />
      </div>

      {/* Filter and Search Bar */}
      <div className="toolbar-bar">
        <div className="filter-tabs">
          <button
            type="button"
            className={`filter-tab-btn ${statusFilter === 'pending' ? 'is-active' : ''}`}
            onClick={() => setStatusFilter('pending')}
          >
            Pending
            <span className="filter-badge-count">{stats.pending}</span>
          </button>
          <button
            type="button"
            className={`filter-tab-btn ${statusFilter === 'approved' ? 'is-active' : ''}`}
            onClick={() => setStatusFilter('approved')}
          >
            Approved
            <span className="filter-badge-count">{stats.approved}</span>
          </button>
          <button
            type="button"
            className={`filter-tab-btn ${statusFilter === 'rejected' ? 'is-active' : ''}`}
            onClick={() => setStatusFilter('rejected')}
          >
            Rejected
            <span className="filter-badge-count">{stats.rejected}</span>
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
            className={`filter-tab-btn ${statusFilter === 'all' ? 'is-active' : ''}`}
            onClick={() => setStatusFilter('all')}
          >
            All Requests
            <span className="filter-badge-count">{stats.total}</span>
          </button>
        </div>

        <div className="search-input-wrap">
          <Search size={14} className="search-icon" />
          <input
            type="text"
            className="search-input"
            placeholder="Filter by requester, resource, or ID..."
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

      {/* Table Section */}
      <div className="table-wrapper">
        <table className="admin-table">
          <thead>
            <tr>
              <th style={{ width: '70px' }}>ID</th>
              <th>Requester</th>
              <th>Resource</th>
              <th>Requested Validity (IST)</th>
              <th>Purpose</th>
              <th style={{ width: '100px' }}>Status</th>
              <th style={{ width: '130px' }}>Created</th>
              <th style={{ textAlign: 'right', width: '160px' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={8} style={{ textAlign: 'center', padding: '36px' }}>
                  <div className="btn-spinner" style={{ margin: '0 auto 8px', width: '18px', height: '18px' }} />
                  <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Loading access requests...</span>
                </td>
              </tr>
            ) : filteredRequests.length === 0 ? (
              <tr>
                <td colSpan={8}>
                  <div className="empty-state">
                    <div className="empty-state-icon">
                      <Clock size={20} />
                    </div>
                    <div className="empty-state-title">No access requests found</div>
                    <div className="empty-state-desc">
                      {statusFilter === 'pending'
                        ? 'There are currently no access requests pending review.'
                        : `No records matching status "${statusFilter}" and search query "${searchQuery}".`}
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
              filteredRequests.map((req) => {
                const duration = calculateDuration(req.start_at, req.end_at);
                const isPending = req.status === 'pending';

                return (
                  <tr key={req.id}>
                    <td>
                      <span className="id-badge">#{req.id}</span>
                    </td>
                    <td>
                      <div className="user-cell">
                        <span className="user-cell-name">{req.user?.full_name}</span>
                        <span className="user-cell-email">{req.user?.email}</span>
                      </div>
                    </td>
                    <td>
                      <div className="resource-pill">
                        <span className="resource-code">{req.resource?.code}</span>
                        <div>
                          <div className="resource-name">{req.resource?.name}</div>
                          <span className="resource-kind">{req.resource?.kind}</span>
                        </div>
                      </div>
                    </td>
                    <td>
                      <div className="time-cell">
                        <span className="time-window">{formatTimeRange(req.start_at, req.end_at)}</span>
                        {duration && <span className="time-meta">Duration: {duration}</span>}
                      </div>
                    </td>
                    <td>
                      <div className="purpose-cell" title={req.purpose}>
                        {req.purpose || '—'}
                      </div>
                    </td>
                    <td>
                      <Badge status={req.status} />
                    </td>
                    <td>
                      <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                        {formatIstDateTime(req.created_at)}
                      </span>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <div className="table-actions" style={{ justifyContent: 'flex-end' }}>
                        {isPending ? (
                          <>
                            <Button
                              size="sm"
                              variant="primary"
                              icon={Check}
                              onClick={() => handleOpenApprove(req)}
                              title="Approve access request and generate credential"
                            >
                              Approve
                            </Button>
                            <Button
                              size="sm"
                              variant="danger"
                              icon={X}
                              onClick={() => handleOpenReject(req)}
                              title="Reject access request"
                            >
                              Reject
                            </Button>
                          </>
                        ) : (
                          <Button
                            size="sm"
                            variant="secondary"
                            icon={Info}
                            onClick={() => setDetailModal({ isOpen: true, request: req })}
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

      {/* Approve Confirmation Modal */}
      <Modal
        isOpen={approveModal.isOpen}
        onClose={() => setApproveModal((prev) => ({ ...prev, isOpen: false }))}
        title="Approve Access Request"
        subtitle={`Request #${approveModal.request?.id} — ${approveModal.request?.user?.full_name}`}
        icon={Shield}
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setApproveModal((prev) => ({ ...prev, isOpen: false }))}
              disabled={approveModal.isSubmitting}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={handleConfirmApprove}
              loading={approveModal.isSubmitting}
              icon={Check}
            >
              Confirm & Issue Key
            </Button>
          </>
        }
      >
        {approveModal.request && (
          <>
            {/* Request Summary */}
            <div className="modal-summary-box">
              <div className="summary-row">
                <span className="summary-key">Resource:</span>
                <span className="summary-val">
                  {approveModal.request.resource?.name} (Code: {approveModal.request.resource?.code})
                </span>
              </div>
              <div className="summary-row">
                <span className="summary-key">Validity Window:</span>
                <span className="summary-val" style={{ fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                  {formatTimeRange(approveModal.request.start_at, approveModal.request.end_at)}
                </span>
              </div>
              <div className="summary-row">
                <span className="summary-key">Requester Purpose:</span>
                <span className="summary-val" style={{ fontWeight: 400 }}>
                  {approveModal.request.purpose}
                </span>
              </div>
            </div>

            {/* Rule R1 Conflict Warning */}
            {approveModal.activeCredentialConflict ? (
              <div className="alert-box alert-warning">
                <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: '2px' }} />
                <div>
                  <div style={{ fontWeight: 600, marginBottom: '2px' }}>
                    Rule R1 Conflict: Active Key Already Exists
                  </div>
                  <div>
                    Resource <strong>{approveModal.request.resource?.code}</strong> currently has active credential{' '}
                    <strong>#{approveModal.activeCredentialConflict.id}</strong> ({approveModal.activeCredentialConflict.user?.full_name}).
                    Per Rule R1, only one active credential may exist per physical latch.
                  </div>
                  <label className="alert-checkbox-row">
                    <input
                      type="checkbox"
                      checked={approveModal.replaceExisting}
                      onChange={(e) =>
                        setApproveModal((prev) => ({
                          ...prev,
                          replaceExisting: e.target.checked,
                          errorMessage: ''
                        }))
                      }
                    />
                    <span>
                      <strong>Replace existing credential</strong> (revokes active key on next device sync).
                    </span>
                  </label>
                </div>
              </div>
            ) : (
              <div className="alert-box alert-info">
                <CheckCircle2 size={16} style={{ flexShrink: 0, marginTop: '1px' }} />
                <div>
                  Resource <strong>{approveModal.request.resource?.code}</strong> is currently unreserved.
                  An active key will be generated immediately for the requested window.
                </div>
              </div>
            )}

            {/* Admin Decision Note Input */}
            <div className="modal-field">
              <label htmlFor="approve-note" className="field-label">
                Decision Note (Optional):
              </label>
              <input
                id="approve-note"
                type="text"
                className="field-input"
                placeholder="e.g. Approved for laboratory session"
                value={approveModal.note}
                onChange={(e) =>
                  setApproveModal((prev) => ({ ...prev, note: e.target.value }))
                }
              />
            </div>

            {/* Error Message */}
            {approveModal.errorMessage && (
              <div className="alert-box alert-danger">
                <AlertTriangle size={16} style={{ flexShrink: 0 }} />
                <span>{approveModal.errorMessage}</span>
              </div>
            )}
          </>
        )}
      </Modal>

      {/* Reject Confirmation Modal */}
      <Modal
        isOpen={rejectModal.isOpen}
        onClose={() => setRejectModal((prev) => ({ ...prev, isOpen: false }))}
        title="Reject Access Request"
        subtitle={`Request #${rejectModal.request?.id} — ${rejectModal.request?.user?.full_name}`}
        icon={XCircle}
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setRejectModal((prev) => ({ ...prev, isOpen: false }))}
              disabled={rejectModal.isSubmitting}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={handleConfirmReject}
              loading={rejectModal.isSubmitting}
              icon={X}
            >
              Confirm Rejection
            </Button>
          </>
        }
      >
        {rejectModal.request && (
          <>
            <div className="modal-summary-box">
              <div className="summary-row">
                <span className="summary-key">Resource:</span>
                <span className="summary-val">{rejectModal.request.resource?.name}</span>
              </div>
              <div className="summary-row">
                <span className="summary-key">Requester:</span>
                <span className="summary-val">{rejectModal.request.user?.full_name}</span>
              </div>
            </div>

            <div className="modal-field">
              <label htmlFor="reject-note" className="field-label">
                Rejection Reason / Note:
              </label>
              <textarea
                id="reject-note"
                className="field-textarea"
                placeholder="Explain why this request is declined..."
                value={rejectModal.note}
                onChange={(e) =>
                  setRejectModal((prev) => ({ ...prev, note: e.target.value }))
                }
              />
            </div>

            {rejectModal.errorMessage && (
              <div className="alert-box alert-danger">
                <AlertTriangle size={16} style={{ flexShrink: 0 }} />
                <span>{rejectModal.errorMessage}</span>
              </div>
            )}
          </>
        )}
      </Modal>

      {/* Detail Modal */}
      <Modal
        isOpen={detailModal.isOpen}
        onClose={() => setDetailModal({ isOpen: false, request: null })}
        title={`Access Request #${detailModal.request?.id}`}
        subtitle={`Status: ${detailModal.request?.status?.toUpperCase()}`}
        icon={FileText}
        footer={
          <Button
            variant="secondary"
            onClick={() => setDetailModal({ isOpen: false, request: null })}
          >
            Close
          </Button>
        }
      >
        {detailModal.request && (
          <div className="modal-summary-box">
            <div className="summary-row">
              <span className="summary-key">Status:</span>
              <span className="summary-val">
                <Badge status={detailModal.request.status} />
              </span>
            </div>
            <div className="summary-row">
              <span className="summary-key">Requester:</span>
              <span className="summary-val">{detailModal.request.user?.full_name} ({detailModal.request.user?.email})</span>
            </div>
            <div className="summary-row">
              <span className="summary-key">Resource:</span>
              <span className="summary-val">
                {detailModal.request.resource?.name} [{detailModal.request.resource?.code}]
              </span>
            </div>
            <div className="summary-row">
              <span className="summary-key">Requested Window:</span>
              <span className="summary-val" style={{ fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                {formatTimeRange(detailModal.request.start_at, detailModal.request.end_at)}
              </span>
            </div>
            <div className="summary-row">
              <span className="summary-key">Submitted At:</span>
              <span className="summary-val" style={{ fontSize: '11px' }}>
                {formatIstDateTime(detailModal.request.created_at)}
              </span>
            </div>
            {detailModal.request.decided_at && (
              <div className="summary-row">
                <span className="summary-key">Decided At:</span>
                <span className="summary-val" style={{ fontSize: '11px' }}>
                  {formatIstDateTime(detailModal.request.decided_at)}
                </span>
              </div>
            )}
            {detailModal.request.decision_note && (
              <div className="summary-row">
                <span className="summary-key">Decision Note:</span>
                <span className="summary-val" style={{ fontWeight: 400 }}>
                  {detailModal.request.decision_note}
                </span>
              </div>
            )}
            {detailModal.request.credential && (
              <div className="summary-row" style={{ marginTop: '8px', borderTop: '1px solid var(--border-subtle)', paddingTop: '8px' }}>
                <span className="summary-key">Issued Credential:</span>
                <span className="summary-val">
                  #{detailModal.request.credential.id} ({detailModal.request.credential.status})
                </span>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
