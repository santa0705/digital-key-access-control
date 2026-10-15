import { useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import AdminPending from './pages/AdminPending';
import AdminCredentials from './pages/AdminCredentials';
import AdminLogs from './pages/AdminLogs';
import UserPortalStub from './pages/UserPortalStub';
import NotFound from './pages/NotFound';
import Toast from './components/Toast';
import { adminApi } from './services/adminApi';
import './components/components.css';

export default function App() {
  const [globalToast, setGlobalToast] = useState(null);
  const [resetCounter, setResetCounter] = useState(0);

  const handleResetMockData = () => {
    adminApi.resetMockData();
    setResetCounter((prev) => prev + 1);
    setGlobalToast({
      type: 'info',
      message: 'Mock state has been reset to initial baseline values.'
    });
  };

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/"
          element={
            <Layout
              key={resetCounter}
              onResetMockData={handleResetMockData}
              toast={
                globalToast && (
                  <Toast
                    type={globalToast.type}
                    message={globalToast.message}
                    onClose={() => setGlobalToast(null)}
                  />
                )
              }
            />
          }
        >
          {/* Default landing redirects to Admin Pending */}
          <Route index element={<Navigate to="/admin/pending" replace />} />

          {/* Admin Pending Access Requests */}
          <Route path="admin/pending" element={<AdminPending key={resetCounter} />} />
          <Route path="admin/access-requests" element={<Navigate to="/admin/pending" replace />} />

          {/* Admin Issued Credentials */}
          <Route path="admin/credentials" element={<AdminCredentials key={resetCounter} />} />

          {/* Admin Audit Logs (Telemetry Stream) */}
          <Route path="admin/logs" element={<AdminLogs />} />

          {/* User Portal Stub (Preserving Person A's routes) */}
          <Route path="access-requests" element={<UserPortalStub />} />

          {/* Fallback 404 Route */}
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
