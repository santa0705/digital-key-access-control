import { Link } from 'react-router-dom';
import { AlertTriangle, Home } from 'lucide-react';
import Button from '../components/Button';

export default function NotFound() {
  return (
    <div className="admin-page-container" style={{ textAlign: 'center', padding: '80px 20px' }}>
      <div className="empty-state">
        <div className="empty-state-icon" style={{ width: '56px', height: '56px' }}>
          <AlertTriangle size={24} style={{ color: 'var(--status-pending-text)' }} />
        </div>
        <h1 className="empty-state-title" style={{ fontSize: '20px' }}>404 — Page Not Found</h1>
        <p className="empty-state-desc">
          The requested administrative or user path does not exist in the digital key access system.
        </p>
        <Link to="/admin/pending">
          <Button variant="primary" icon={Home}>
            Return to Admin Console
          </Button>
        </Link>
      </div>
    </div>
  );
}
