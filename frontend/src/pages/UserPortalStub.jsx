import { Link } from 'react-router-dom';
import { User, Shield, Clock } from 'lucide-react';
import Button from '../components/Button';

export default function UserPortalStub() {
  return (
    <div className="admin-page-container" style={{ maxWidth: '720px', margin: '40px auto' }}>
      <div className="page-header" style={{ marginBottom: '16px' }}>
        <div>
          <h1 className="page-title">User Access Portal</h1>
          <p className="page-description">
            Person A module placeholder (<code>/access-requests</code>, <code>/resources</code>).
          </p>
        </div>
      </div>

      <div className="modal-summary-box" style={{ padding: '24px', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div
            style={{
              width: '40px',
              height: '40px',
              borderRadius: 'var(--radius-sm)',
              background: 'var(--accent-green-light)',
              border: '1px solid var(--accent-green-border)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--accent-green)'
            }}
          >
            <User size={20} />
          </div>
          <div>
            <h3 style={{ fontSize: '15px', fontWeight: 600 }}>Requester Self-Service Portal</h3>
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
              Allows standard users to view available lockers, book physical access windows, and reveal single-use PINs.
            </p>
          </div>
        </div>

        <div className="alert-box alert-info">
          <Clock size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
          <div>
            <strong>Person A Scope Separation:</strong> User request submission (<code>POST /access-requests</code>)
            and owner PIN reveal (<code>GET /access-requests/&#123;id&#125;/pin</code>) are assigned to Person A.
            Person B&apos;s administrative approval and credential invalidation modules are fully operational in the Admin Console.
          </div>
        </div>

        <div style={{ display: 'flex', gap: '10px', marginTop: '8px' }}>
          <Link to="/admin/pending">
            <Button variant="primary" icon={Shield}>
              Go to Admin Pending Approvals
            </Button>
          </Link>
          <Link to="/admin/credentials">
            <Button variant="secondary">
              Go to Issued Credentials
            </Button>
          </Link>
        </div>
      </div>
    </div>
  );
}
