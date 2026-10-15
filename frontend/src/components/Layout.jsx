import { useState, useEffect } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  Shield,
  Key,
  Clock,
  RotateCcw,
  Menu,
  X,
  ExternalLink,
  CheckCircle,
  FileText,
  User
} from 'lucide-react';
import { adminApi } from '../services/adminApi';

export default function Layout({ onResetMockData, toast }) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [stats, setStats] = useState({ pending: 0, activeCreds: 0 });
  const location = useLocation();

  // Keep badge counts updated in navigation
  useEffect(() => {
    async function loadCounts() {
      try {
        const [requests, creds] = await Promise.all([
          adminApi.getAccessRequests('all'),
          adminApi.getCredentials('all')
        ]);
        const pendingCount = requests.filter((r) => r.status === 'pending').length;
        const activeCount = creds.filter((c) => c.status === 'active').length;
        setStats({ pending: pendingCount, activeCreds: activeCount });
      } catch (err) {
        console.warn('Failed to load nav counts', err);
      }
    }
    loadCounts();
  }, [location.pathname]);

  return (
    <div className="admin-app-layout">
      {/* Top Header */}
      <header className="admin-topbar">
        <div className="topbar-left">
          <button
            type="button"
            className="mobile-nav-toggle"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle navigation menu"
          >
            {mobileMenuOpen ? <X size={18} /> : <Menu size={18} />}
          </button>

          <div className="brand-logo">
            <div className="brand-icon-box">
              <Shield size={18} className="brand-icon" />
            </div>
            <div className="brand-text">
              <span className="brand-title">DIGITAL KEY</span>
              <span className="brand-subtitle">Access Control Admin</span>
            </div>
          </div>

          <div className="system-status-indicator" title="ESP32 nodes time anchor window: 90s fail-closed">
            <span className="status-dot-pulse" />
            <span className="status-text">Server-Anchored</span>
            <span className="status-meta">Epoch 8b9f • 90s Window</span>
          </div>
        </div>

        <div className="topbar-right">
          <button
            type="button"
            className="btn-reset-mock"
            onClick={onResetMockData}
            title="Reset mock requests and credentials to original state"
          >
            <RotateCcw size={13} />
            <span>Reset Mock State</span>
          </button>

          <div className="admin-user-badge">
            <div className="user-avatar">AD</div>
            <div className="user-details">
              <span className="user-name">Admin Officer</span>
              <span className="user-email">admin@demo.local</span>
            </div>
          </div>
        </div>
      </header>

      {/* Main Container with Sidebar + Content */}
      <div className="admin-main-container">
        {/* Navigation Sidebar */}
        <aside className={`admin-sidebar ${mobileMenuOpen ? 'mobile-open' : ''}`}>
          <div className="sidebar-section-title">ADMINISTRATION</div>
          <nav className="sidebar-nav">
            <NavLink
              to="/admin/pending"
              onClick={() => setMobileMenuOpen(false)}
              className={({ isActive }) =>
                `nav-item ${isActive ? 'is-active' : ''}`
              }
            >
              <Clock size={16} className="nav-icon" />
              <span className="nav-label">Pending Requests</span>
              {stats.pending > 0 && (
                <span className="nav-counter count-pending">{stats.pending}</span>
              )}
            </NavLink>

            <NavLink
              to="/admin/credentials"
              onClick={() => setMobileMenuOpen(false)}
              className={({ isActive }) =>
                `nav-item ${isActive ? 'is-active' : ''}`
              }
            >
              <Key size={16} className="nav-icon" />
              <span className="nav-label">Issued Credentials</span>
              {stats.activeCreds > 0 && (
                <span className="nav-counter count-active">{stats.activeCreds}</span>
              )}
            </NavLink>

            <NavLink
              to="/admin/logs"
              onClick={() => setMobileMenuOpen(false)}
              className={({ isActive }) =>
                `nav-item ${isActive ? 'is-active' : ''}`
              }
            >
              <FileText size={16} className="nav-icon" />
              <span className="nav-label">Audit Logs</span>
              <span className="nav-tag">Live</span>
            </NavLink>
          </nav>

          <div className="sidebar-divider" />

          <div className="sidebar-section-title">USER SERVICES</div>
          <nav className="sidebar-nav">
            <NavLink
              to="/access-requests"
              onClick={() => setMobileMenuOpen(false)}
              className={({ isActive }) =>
                `nav-item nav-item-external ${isActive ? 'is-active' : ''}`
              }
            >
              <User size={16} className="nav-icon" />
              <span className="nav-label">User Request Portal</span>
              <ExternalLink size={12} className="nav-external-icon" />
            </NavLink>
          </nav>

          <div className="sidebar-footer-box">
            <div className="footer-box-title">Rule R1 Enforcement</div>
            <p className="footer-box-desc">
              Strictly 1 active credential per physical resource. Superseded credentials revoke automatically.
            </p>
            <div className="footer-box-pill">
              <CheckCircle size={12} />
              <span>contracts-v1 Active</span>
            </div>
          </div>
        </aside>

        {/* Content Area */}
        <main className="admin-content-area">
          {toast}
          <Outlet />
        </main>
      </div>
    </div>
  );
}
