import { useState } from 'react';
import { LogIn, Lock, Mail, AlertCircle, Shield, User } from 'lucide-react';
import Modal from './Modal';
import Button from './Button';
import { adminApi } from '../services/adminApi';

export default function LoginModal({ isOpen, onClose, onSuccess }) {
  const [email, setEmail] = useState('admin@demo.local');
  const [password, setPassword] = useState('demo-password');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  const handleSubmit = async (e) => {
    if (e) e.preventDefault();
    if (!email.trim() || !password) {
      setErrorMessage('Please enter both email and password.');
      return;
    }

    setIsSubmitting(true);
    setErrorMessage('');

    try {
      const data = await adminApi.login({
        email: email.trim(),
        password
      });

      if (onSuccess) {
        onSuccess(data.user);
      }
      onClose();
    } catch (err) {
      if (err.code === 'invalid_credentials') {
        setErrorMessage('Invalid email or password.');
      } else if (err.code === 'network_error') {
        setErrorMessage(`Network error: Could not reach backend at ${adminApi.getBaseUrl()}. Please ensure the FastAPI server is running.`);
      } else {
        setErrorMessage(err.message || 'Authentication failed.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleFillDemo = (demoEmail) => {
    setEmail(demoEmail);
    setPassword('demo-password');
    setErrorMessage('');
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Sign In to Digital Key"
      subtitle="Authenticate with your credentials to obtain a secure Bearer session token"
      icon={LogIn}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button variant="primary" icon={LogIn} loading={isSubmitting} onClick={handleSubmit}>
            Sign In
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {errorMessage && (
          <div className="alert-box alert-danger">
            <AlertCircle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
            <div>{errorMessage}</div>
          </div>
        )}

        <div className="form-group">
          <label className="form-label" htmlFor="login-email">
            Email Address
          </label>
          <div style={{ position: 'relative' }}>
            <input
              id="login-email"
              type="email"
              className="form-input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="e.g. admin@demo.local"
              required
              disabled={isSubmitting}
            />
          </div>
        </div>

        <div className="form-group">
          <label className="form-label" htmlFor="login-password">
            Password
          </label>
          <div style={{ position: 'relative' }}>
            <input
              id="login-password"
              type="password"
              className="form-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••••••"
              required
              disabled={isSubmitting}
            />
          </div>
        </div>

        <div style={{ background: 'var(--bg-secondary)', padding: '12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-color)' }}>
          <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '8px' }}>
            Local Development Quick Fill
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => handleFillDemo('admin@demo.local')}
              disabled={isSubmitting}
              style={{ fontSize: '11px' }}
            >
              <Shield size={12} />
              <span>Admin (admin@demo.local)</span>
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => handleFillDemo('user@demo.local')}
              disabled={isSubmitting}
              style={{ fontSize: '11px' }}
            >
              <User size={12} />
              <span>User (user@demo.local)</span>
            </button>
          </div>
        </div>
      </form>
    </Modal>
  );
}
