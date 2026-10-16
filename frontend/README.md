# Digital Key Access Control â€” Management Console Frontend

A high-performance, responsive Single Page Application (SPA) built with **React 19** and **Vite** for administrators and users of the Digital Key Access Control system.

---

## 1. Overview & Key Capabilities

- **Admin Dashboard & Approval Queue:** Review and approve or reject pending access requests with automated conflict detection and replacement handling.
- **Resource & Credential Management:** Real-time visibility into active access keys for physical lockers (Resource A) and virtual lockers (Resource B), with instant one-click revocation.
- **Unified Audit Logs:** Filterable real-time event stream combining server-side administrative actions and device-side telemetry (unlocks, invalid PIN rejections, lockout triggers).
- **User Self-Service Portal:** Interactive interface for requesting access windows and securely revealing issued 6-digit PIN keys.
- **Design System:** Polished modern UI with curated color palettes, accessible interactive controls, Lucide icons, and `@fontsource/inter` typography.

---

## 2. Technology Stack

| Layer | Technology | Version | Purpose |
|---|---|---|---|
| **Core UI Library** | React | 19.2.x | Component lifecycle and reactive state management. |
| **Routing** | React Router | 7.18.x | Client-side declarative routing and layout nesting. |
| **Build Tool & Bundler** | Vite | 8.3.x | Fast Hot Module Replacement (HMR) and optimized Rollup production bundling. |
| **Typography** | @fontsource/inter | 5.3.x | Zero-latency self-hosted Inter font bundle. |
| **Icons** | Lucide React | 1.55.x | Consistent, accessible SVG iconography. |
| **Linter** | ESLint | 10.x | Flat config linter with React Hooks and Refresh rules. |
| **Test Runner** | Node.js Test Runner | Built-in | Fast zero-dependency contract and date/time unit testing. |

---

## 3. Project Structure

```
frontend/
â”œâ”€â”€ public/                 # Static assets (favicons, SVG icons)
â”œâ”€â”€ src/
â”‚   â”œâ”€â”€ assets/             # Brand graphics and images
â”‚   â”œâ”€â”€ components/         # Reusable UI components (Modal, Button, Badge, Toast, Layout)
â”‚   â”œâ”€â”€ pages/              # Primary route views:
â”‚   â”‚   â”œâ”€â”€ AdminCredentials.jsx   # Credential revocation and active keys
â”‚   â”‚   â”œâ”€â”€ AdminLogs.jsx          # Unified audit trail viewer
â”‚   â”‚   â”œâ”€â”€ AdminPending.jsx       # Request approval / rejection workflow
â”‚   â”‚   â”œâ”€â”€ UserPortalStub.jsx     # User access request and PIN reveal
â”‚   â”‚   â””â”€â”€ NotFound.jsx           # 404 error page
â”‚   â”œâ”€â”€ services/           # Backend API integration:
â”‚   â”‚   â”œâ”€â”€ adminApi.js            # Admin domain endpoints
â”‚   â”‚   â”œâ”€â”€ apiClient.js           # Fetch wrapper with Bearer token injection & error handling
â”‚   â”‚   â””â”€â”€ mockData.js            # Initial demonstration stubs
â”‚   â”œâ”€â”€ utils/              # Utilities (IST date formatting, credential status calculator)
â”‚   â”œâ”€â”€ App.jsx             # Route definitions and session providers
â”‚   â”œâ”€â”€ main.jsx            # React root mount
â”‚   â””â”€â”€ index.css           # Global tokens and CSS design system
â”œâ”€â”€ tests/                  # Automated integration and unit tests:
â”‚   â”œâ”€â”€ apiClient.test.js   # Contract path, header, and error envelope tests
â”‚   â””â”€â”€ dateUtils.test.js   # IST (+05:30) date formatting and lifecycle tests
â”œâ”€â”€ vercel.json             # Vercel SPA routing rewrite rules
â””â”€â”€ vite.config.js          # Vite build configuration
```

---

## 4. Development & Build Commands

All commands are executed from the `frontend/` directory:

```bash
# Install dependencies
npm install

# Start local development server (http://localhost:5173)
npm run dev

# Run automated tests (25 passing unit & contract tests)
npm test

# Run ESLint code checks
npm run lint

# Compile production bundle to dist/
npm run build

# Preview production build locally
npm run preview
```

---

## 5. Configuration & Environment Variables

Copy `.env.example` to `.env` to configure the backend API endpoint:

```ini
# Base URL of the FastAPI Backend
VITE_API_BASE_URL=http://localhost:8000
```

When deployed to production (e.g. Vercel), configure `VITE_API_BASE_URL` in the hosting dashboard to point to your live backend (e.g. `https://digital-key-backend-2qvp.onrender.com`).

---

## 6. Deployment

The frontend includes `vercel.json` configuring client-side SPA rewrites:

```json
{
  "rewrites": [
    {
      "source": "/(.*)",
      "destination": "/index.html"
    }
  ]
}
```

Deploy directly using Vercel CLI or by connecting your GitHub repository to Vercel.
