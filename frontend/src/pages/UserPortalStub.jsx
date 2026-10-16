import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  Shield,
  Clock,
  Key,
  Eye,
  EyeOff,
  Send,
  RefreshCw,
  Lock,
  Layers
} from 'lucide-react';
import Button from '../components/Button';
import Badge from '../components/Badge';
import Toast from '../components/Toast';
import { adminApi } from '../services/adminApi';
import { formatIstDateTime, getEffectiveCredentialStatus } from '../utils/dateUtils';

export default function UserPortalStub() {
  const [resources, setResources] = useState([]);
  const [myRequests, setMyRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);

  // New Request Form State
  const [selectedResourceId, setSelectedResourceId] = useState('');
  const [startAt, setStartAt] = useState(() => {
    const now = new Date();
    now.setMinutes(Math.ceil(now.getMinutes() / 5) * 5, 0, 0);
    return now.toISOString().replace(/\.\d{3}Z$/, 'Z');
  });
  const [durationHours, setDurationHours] = useState('1');
  const [purpose, setPurpose] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Transient PIN reveals (stored ONLY in memory, never in localStorage or console)
  const [revealedPins, setRevealedPins] = useState({});
  const [pinLoadingId, setPinLoadingId] = useState(null);

  const loadPortalData = async () => {
    setLoading(true);
    try {
      const [resList, reqList] = await Promise.all([
        adminApi.getResources().catch(() => []),
        adminApi.getMyAccessRequests().catch(() => [])
      ]);

      const validResources = Array.isArray(resList) ? resList : [];
      setResources(validResources);
      if (validResources.length > 0 && !selectedResourceId) {
        setSelectedResourceId(String(validResources[0].id));
      }
      setMyRequests(Array.isArray(reqList) ? reqList : []);
    } catch (err) {
      setToast({
        type: 'error',
        message: err.code === 'unauthorized'
          ? 'Authentication required. Please sign in.'
          : err.message || 'Failed to load user portal data'
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let ignore = false;
    Promise.all([
      adminApi.getResources().catch(() => []),
      adminApi.getMyAccessRequests().catch(() => [])
    ])
      .then(([resList, reqList]) => {
        if (!ignore) {
          const validResources = Array.isArray(resList) ? resList : [];
          setResources(validResources);
          if (validResources.length > 0) {
            setSelectedResourceId(prev => prev || String(validResources[0].id));
          }
          setMyRequests(Array.isArray(reqList) ? reqList : []);
          setLoading(false);
        }
      })
      .catch(err => {
        if (!ignore) {
          setToast({
            type: 'error',
            message: err.code === 'unauthorized'
              ? 'Authentication required. Please sign in.'
              : err.message || 'Failed to load user portal data'
          });
          setLoading(false);
        }
      });
    return () => {
      ignore = true;
    };
  }, []);

  // Submit Access Request
  const handleSubmitRequest = async (e) => {
    if (e) e.preventDefault();
    if (!selectedResourceId) {
      setToast({ type: 'error', message: 'Please select a resource' });
      return;
    }

    try {
      setIsSubmitting(true);
      const startDt = new Date(startAt);
      const endDt = new Date(startDt.getTime() + Number(durationHours) * 3600 * 1000);
      const endIso = endDt.toISOString().replace(/\.\d{3}Z$/, 'Z');

      const created = await adminApi.createAccessRequest({
        resource_id: Number(selectedResourceId),
        start_at: startAt,
        end_at: endIso,
        purpose: purpose.trim() || undefined
      });

      setToast({
        type: 'success',
        message: `Access request #${created.id} submitted successfully with status "${created.status}".`
      });

      setPurpose('');
      loadPortalData();
    } catch (err) {
      setToast({
        type: 'error',
        message: err.message || 'Failed to submit access request'
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  // Reveal PIN for approved request with active credential
  const handleRevealPin = async (requestId) => {
    if (revealedPins[requestId]) {
      // Toggle off
      setRevealedPins((prev) => {
        const next = { ...prev };
        delete next[requestId];
        return next;
      });
      return;
    }

    setPinLoadingId(requestId);
    try {
      const pinData = await adminApi.revealPin(requestId);
      // Store transiently in component state only
      setRevealedPins((prev) => ({
        ...prev,
        [requestId]: pinData
      }));
    } catch (err) {
      setToast({
        type: 'error',
        message: err.message || 'Failed to reveal PIN. Ensure request is approved and active.'
      });
    } finally {
      setPinLoadingId(null);
    }
  };

  return (
    <div className="admin-page-container" style={{ maxWidth: '960px', margin: '0 auto' }}>
      {toast && (
        <Toast
          type={toast.type}
          message={toast.message}
          onClose={() => setToast(null)}
        />
      )}

      <div className="page-header" style={{ marginBottom: '24px' }}>
        <div>
          <h1 className="page-title">User Access Portal</h1>
          <p className="page-description">
            Request locker access, track approvals, and securely retrieve single-use credentials (<code>/access-requests</code>, <code>/resources</code>).
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <Button variant="secondary" icon={RefreshCw} onClick={loadPortalData} disabled={loading} loading={loading}>
            Refresh
          </Button>
          <Link to="/admin/pending">
            <Button variant="secondary" icon={Shield}>
              Admin Console
            </Button>
          </Link>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '28px' }}>
        {/* Request Form */}
        <div className="card" style={{ padding: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
            <Send size={16} style={{ color: 'var(--accent-primary)' }} />
            <h3 style={{ fontSize: '15px', fontWeight: 600 }}>Submit Access Request</h3>
          </div>

          <form onSubmit={handleSubmitRequest} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <div className="form-group">
              <label className="form-label" htmlFor="portal-resource">
                Select Resource
              </label>
              <select
                id="portal-resource"
                className="form-input"
                value={selectedResourceId}
                onChange={(e) => setSelectedResourceId(e.target.value)}
                disabled={isSubmitting || resources.length === 0}
              >
                {resources.length === 0 ? (
                  <option value="">No resources loaded</option>
                ) : (
                  resources.map((res) => (
                    <option key={res.id} value={res.id}>
                      [{res.code}] {res.name} ({res.kind})
                    </option>
                  ))
                )}
              </select>
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="portal-start">
                Start Time (UTC ISO-8601)
              </label>
              <input
                id="portal-start"
                type="text"
                className="form-input"
                value={startAt}
                onChange={(e) => setStartAt(e.target.value)}
                placeholder="2026-10-15T09:00:00Z"
                required
                disabled={isSubmitting}
              />
              {startAt && (
                <span style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '4px', display: 'block' }}>
                  Equivalent IST: {formatIstDateTime(startAt)}
                </span>
              )}
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="portal-duration">
                Duration (Hours)
              </label>
              <select
                id="portal-duration"
                className="form-input"
                value={durationHours}
                onChange={(e) => setDurationHours(e.target.value)}
                disabled={isSubmitting}
              >
                <option value="1">1 Hour</option>
                <option value="2">2 Hours</option>
                <option value="4">4 Hours</option>
                <option value="8">8 Hours</option>
              </select>
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="portal-purpose">
                Purpose / Note
              </label>
              <input
                id="portal-purpose"
                type="text"
                className="form-input"
                value={purpose}
                onChange={(e) => setPurpose(e.target.value)}
                placeholder="e.g. Equipment inspection"
                disabled={isSubmitting}
              />
            </div>

            <Button
              variant="primary"
              icon={Send}
              loading={isSubmitting}
              onClick={handleSubmitRequest}
              style={{ marginTop: '6px' }}
            >
              Submit Request
            </Button>
          </form>
        </div>

        {/* Resources Overview Card */}
        <div className="card" style={{ padding: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
            <Layers size={16} style={{ color: 'var(--accent-primary)' }} />
            <h3 style={{ fontSize: '15px', fontWeight: 600 }}>Available Physical Resources</h3>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {resources.length === 0 ? (
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                No resources available.
              </div>
            ) : (
              resources.map((res) => (
                <div
                  key={res.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '12px',
                    borderRadius: 'var(--radius-sm)',
                    background: 'var(--bg-secondary)',
                    border: '1px solid var(--border-color)'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span className="resource-code">{res.code}</span>
                    <div>
                      <div style={{ fontSize: '13px', fontWeight: 600 }}>{res.name}</div>
                      <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                        Kind: {res.kind} • Rule R1 Protected
                      </div>
                    </div>
                  </div>
                  <Badge variant={res.is_active ? 'success' : 'neutral'}>
                    {res.is_active ? 'Available' : 'Inactive'}
                  </Badge>
                </div>
              ))
            )}
          </div>

          <div className="alert-box alert-info" style={{ marginTop: '16px' }}>
            <Lock size={14} style={{ flexShrink: 0, marginTop: '2px' }} />
            <div style={{ fontSize: '11px' }}>
              <strong>Rule R1 Policy:</strong> Only one active digital PIN can be valid per physical resource at any time.
            </div>
          </div>
        </div>
      </div>

      {/* User Requests List */}
      <div className="card" style={{ padding: '20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Clock size={16} style={{ color: 'var(--accent-primary)' }} />
            <h3 style={{ fontSize: '15px', fontWeight: 600 }}>My Access Requests</h3>
          </div>
          <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
            Total: {myRequests.length}
          </span>
        </div>

        <div className="table-wrapper">
          <table className="admin-table">
            <thead>
              <tr>
                <th style={{ width: '80px' }}>Req #</th>
                <th>Resource</th>
                <th>Validity Window (IST)</th>
                <th>Status</th>
                <th>Credential / PIN</th>
                <th style={{ textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', padding: '24px' }}>
                    <div className="btn-spinner" style={{ margin: '0 auto 8px', width: '16px', height: '16px' }} />
                    <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Loading your requests...</span>
                  </td>
                </tr>
              ) : myRequests.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', padding: '24px', color: 'var(--text-secondary)' }}>
                    No access requests submitted yet.
                  </td>
                </tr>
              ) : (
                myRequests.map((req) => {
                  const credStatus = getEffectiveCredentialStatus(req.credential);
                  const hasActiveCred = credStatus === 'active';
                  const pinData = revealedPins[req.id];

                  return (
                    <tr key={req.id}>
                      <td>
                        <span className="id-badge">#{req.id}</span>
                      </td>
                      <td>
                        <span className="resource-code">{req.resource?.code}</span>
                        <span style={{ fontSize: '12px', marginLeft: '6px' }}>{req.resource?.name}</span>
                      </td>
                      <td>
                        <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                          {formatIstDateTime(req.start_at)}
                          <br />
                          {formatIstDateTime(req.end_at)}
                        </div>
                      </td>
                      <td>
                        <Badge
                          variant={
                            req.status === 'approved'
                              ? 'success'
                              : req.status === 'pending'
                              ? 'warning'
                              : req.status === 'rejected'
                              ? 'danger'
                              : 'neutral'
                          }
                        >
                          {req.status}
                        </Badge>
                      </td>
                      <td>
                        {pinData ? (
                          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', background: '#ecfdf5', padding: '4px 8px', borderRadius: '4px', border: '1px solid #a7f3d0' }}>
                            <Key size={13} style={{ color: '#059669' }} />
                            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, letterSpacing: '2px', color: '#065f46' }}>
                              {pinData.pin}
                            </span>
                          </div>
                        ) : hasActiveCred ? (
                          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
                            •••••• (Ready)
                          </span>
                        ) : (
                          <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                            {req.credential ? `[${credStatus}]` : '—'}
                          </span>
                        )}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {hasActiveCred ? (
                          <Button
                            variant="secondary"
                            size="sm"
                            icon={pinData ? EyeOff : Eye}
                            loading={pinLoadingId === req.id}
                            onClick={() => handleRevealPin(req.id)}
                          >
                            {pinData ? 'Hide PIN' : 'Reveal PIN'}
                          </Button>
                        ) : (
                          <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                            {req.status === 'pending' ? 'Pending Approval' : credStatus === 'expired' ? 'Key Expired' : 'No Active Key'}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
