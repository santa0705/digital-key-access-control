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
  User,
  LogIn,
  LogOut,
  Radio
} from 'lucide-react';
import { adminApi } from '../services/adminApi';
import LoginModal from './LoginModal';

export default function Layout({ onResetMockData, toast }) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [stats, setStats] = useState({ pending: 0, activeCreds: 0 });
  const [currentUser, setCurrentUser] = useState(adminApi.getStoredUser());
  const [isLoginModalOpen, setIsLoginModalOpen] = useState(false);
  const [isDemo, setIsDemo] = useState(adminApi.isDemoMode());
  const location = useLocation();

  // Subscribe to auth changes
  useEffect(() => {
    return adminApi.subscribeAuth((user) => {
      setCurrentUser(user);
    });
  }, []);

  // Keep badge counts updated in navigation
  useEffect(() => {
    async function loadCounts() {
      try {
        const [requests, creds] = await Promise.all([
          adminApi.getAccessRequests('all'),
          adminApi.getCredentials('all')
        ]);
        const pendingCount = (requests || []).filter((r) => r.status === 'pending').length;
        const activeCount = (creds || []).filter((c) => c.status === 'active').length;
        setStats({ pending: pendingCount, activeCreds: activeCount });
      } catch {
        // When unauthenticated or network error, set counts to 0 without breaking UI
        setStats({ pending: 0, activeCreds: 0 });
      }
    }
    loadCounts();
  }, [location.pathname, currentUser, isDemo]);

  const handleLogout = () => {
    adminApi.logout();
    setCurrentUser(null);
  };

  const handleToggleDemoMode = () => {
    const nextMode = !isDemo;
    adminApi.setDemoMode(nextMode);
    setIsDemo(nextMode);
    if (onResetMockData) onResetMockData();
  };

  const userInitials = currentUser?.full_name
    ? currentUser.full_name
        .split(' ')
        .map((n) => n[0])
        .join('')
        .slice(0, 2)
        .toUpperCase()
    : 'AD';

  return (
    <div className="admin-app-layout">
      {/* Login Modal */}
      <LoginModal
        isOpen={isLoginModalOpen}
        onClose={() => setIsLoginModalOpen(false)}
        onSuccess={(user) => {
          setCurrentUser(user);
        }}
      />

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

          <div
            className="system-status-indicator"
            title={isDemo ? 'Running in offline client-side Demo Mode' : `Connected to live FastAPI backend at ${adminApi.getBaseUrl()}`}
          >
            <span className={`status-dot-pulse ${isDemo ? 'status-dot-demo' : ''}`} />
            <span className="status-text">{isDemo ? 'Demo Mode' : 'Live API'}</span>
            <span className="status-meta">
              {isDemo ? 'Mock Fixtures' : adminApi.getBaseUrl().replace('http://', '')}
            </span>
          </div>
        </div>

        <div className="topbar-right">
          {/* Demo Mode Toggle */}
          <button
            type="button"
            className={`btn-reset-mock ${isDemo ? 'active-demo' : ''}`}
            onClick={handleToggleDemoMode}
            title={isDemo ? 'Switch to real FastAPI backend requests' : 'Switch to isolated client-side demo mode'}
          >
            <Radio size={13} />
            <span>{isDemo ? 'Mode: Mock Demo' : 'Mode: Live API'}</span>
          </button>

          {isDemo && (
            <button
              type="button"
              className="btn-reset-mock"
              onClick={onResetMockData}
              title="Reset mock requests and credentials to initial baseline"
            >
              <RotateCcw size={13} />
              <span>Reset Mock State</span>
            </button>
          )}

          {/* User Profile / Auth State */}
          {currentUser ? (
            <div className="admin-user-badge" style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <div className="user-avatar">{userInitials}</div>
              <div className="user-details">
                <span className="user-name">{currentUser.full_name}</span>
                <span className="user-email">{currentUser.email} ({currentUser.role})</span>
              </div>
              <button
                type="button"
                className="btn-icon"
                onClick={handleLogout}
                title="Sign Out"
                style={{
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  color: 'var(--text-secondary)',
                  padding: '4px',
                  display: 'flex',
                  alignItems: 'center'
                }}
              >
                <LogOut size={15} />
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => setIsLoginModalOpen(true)}
              style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}
            >
              <LogIn size={14} />
              <span>Sign In</span>
            </button>
          )}
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
