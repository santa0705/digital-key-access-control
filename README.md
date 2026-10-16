# Digital Key Access Control

> **Secure, Hardware-Enforced Access Management for Shared Physical Resources**
> An end-to-end IoT platform featuring an ESP32 hardware terminal (keypad, 16Ã—2 IÂ²C LCD, servo latch), a robust FastAPI backend with PostgreSQL, and a modern React management dashboard.

[![Backend API Tests](https://img.shields.io/badge/API%20Tests-Passing-brightgreen)]()
[![Frontend Tests](https://img.shields.io/badge/Frontend%20Tests-25%20Passed-brightgreen)]()
[![License](https://img.shields.io/badge/License-Unspecified-lightgrey)](#16-license)

---

## Table of Contents
1. [Project Title & Overview](#1-project-title--overview)
2. [Features](#2-features)
3. [System Architecture](#3-system-architecture)
4. [Hardware Requirements & Wiring](#4-hardware-requirements--wiring)
5. [Software Requirements & Dependencies](#5-software-requirements--dependencies)
6. [Repository Structure](#6-repository-structure)
7. [Installation & Setup](#7-installation--setup)
8. [Configuration & Environment Variables](#8-configuration--environment-variables)
9. [Usage Guide](#9-usage-guide)
10. [API Documentation](#10-api-documentation)
11. [Security Design & Cryptography](#11-security-design--cryptography)
12. [Testing & Troubleshooting](#12-testing--troubleshooting)
13. [Deployment Architecture](#13-deployment-architecture)
14. [Limitations & Future Roadmap](#14-limitations--future-roadmap)
15. [Contributors & Acknowledgements](#15-contributors--acknowledgements)
16. [License](#16-license)

---

## 1. Project Title & Overview

**Digital Key Access Control** is an integrated IoT access-control system designed to solve the security, auditability, and operational challenges of managing shared physical spaces and assets (such as smart lockers, laboratory equipment cages, and restricted resource rooms).

### The Problem It Solves
Traditional mechanical keys and static keypad codes suffer from severe security flaws:
- Static codes are easily shoulder-surfed, copied, and shared among unauthorized individuals.
- Mechanical keys lack audit trails, cannot be revoked remotely, and require physical re-keying when compromised.
- Offline electronic locks often suffer from replay attacks, out-of-sync clocks, and flash memory wear.

### The Solution
This project delivers a multi-tier solution:
1. **Physical Access Terminal (ESP32):** An edge terminal featuring a 4Ã—4 matrix keypad, a 16Ã—2 character IÂ²C LCD, and an SG90 servo motor driving a physical deadbolt latch. It performs local, real-time constant-time PIN authentication against cryptographically salted HMAC digests, queues tamper-evident telemetry events, and securely synchronizes with the cloud via HTTPS.
2. **Central Management Backend (FastAPI):** An asynchronous Python service that manages user identity, handles time-bounded access requests, enforces approval policies (Rule R1: single active key per resource), and exposes a hardened device synchronization protocol with signed response signatures (`X-Server-Signature`).
3. **Web Management Dashboard (React + Vite):** A responsive interface enabling operators to review access requests, revoke active credentials with immediate terminal propagation, inspect real-time audit logs, and monitor terminal connectivity and clock state.

---

## 2. Features

### Implemented & Verified Capabilities
- **Zero Plaintext PIN Storage:** PINs are stored as keyed HMAC-SHA256 digests (`<resource_code>:<pin>`) in the database and terminal cache. Plaintext PINs are encrypted at rest using symmetric Fernet encryption exclusively for authorized owner reveal.
- **Physical Keypad & 16Ã—2 IÂ²C LCD Integration:** Real-time character entry feedback, dynamic resource selection (`A` for physical locker, `B` for simulated locker), clear (`*`), and submit (`#`).
- **Physical Servo Latch Actuation:** Smooth 0Â° (locked) to 180Â° (unlocked) sweep on valid access grant, holding for 3.0 seconds before returning to 0Â° to relock.
- **Local Terminal Evaluation with Offline Resilience:** The terminal validates PINs locally in memory without per-entry network latency and buffers access telemetry events durably during network interruptions.
- **Fail-Closed Clock Synchronization:** Active entry windows require a trusted UTC clock anchored via NTP and signed backend headers.
- **Anti-Brute-Force RAM Lockout:** 3 consecutive incorrect PIN entries trigger an automatic 30-second terminal lockout with live countdown on the LCD.
- **Monotonic Change Synchronization:** Incremental credential synchronization using a gap-free 64-bit sequence counter (`change_seq`).
- **Mutual Device & Server Authentication:** Requests are authenticated via `X-Device-Key` and protected by dynamic nonces; sync responses carry an HMAC-SHA256 signature in `X-Server-Signature` verified by the ESP32.
- **Unified Audit Trail:** A single chronological event log capturing both administrative server events and edge terminal access events.
- **Strict Migration Safety Guard:** Fail-closed Alembic execution guard preventing unauthorized migrations against non-approved databases.

### Deferred / Post-MVP Features
- Advance calendar bookings and recurring schedule reservations.
- Multi-factor biometric (RFID / fingerprint) hardware expansion.
- Local battery-backed RTC module (HW-111 DS1307 disabled during prototype sprint for electrical safety).

---

## 3. System Architecture

The system connects edge hardware, cloud API, relational database, and single-page web application over encrypted protocols:

```mermaid
graph TD
    User([End User / Operator]) -->|Browser HTTPS| Frontend[React + Vite Admin SPA<br/>Vercel Hosting]
    Admin([Administrator]) -->|Browser HTTPS| Frontend
    Frontend -->|REST API + Bearer JWT| Backend[FastAPI Backend Application<br/>Render Python Web Service]
    Backend -->|SQLAlchemy 2 / Psycopg 3| Database[(PostgreSQL Database<br/>Neon / Render Managed DB)]

    Terminal[ESP32 Hardware Terminal<br/>Keypad + LCD + Servo Latch] -->|HTTPS POST /device/v1/sync<br/>TLS GTS Root R4| Backend
    Terminal -->|NTP Time Sync| NTP[NTP Pool Server<br/>pool.ntp.org]

    subgraph Physical Access Terminal
        Terminal --- Keypad[4x4 Matrix Keypad]
        Terminal --- LCD[16x2 I2C Character LCD<br/>DIYables_LCD_I2C]
        Terminal --- Servo[SG90 Latch Servo<br/>180Â° Sweep]
    end
```

### Component Communication Flow
1. **User Request:** User logs in and submits a time-bounded access request via the web interface.
2. **Admin Approval:** Administrator reviews the request. Upon approval, the backend creates an active credential with a cryptographic PIN HMAC and increments `sync_state.change_seq`.
3. **Hardware Sync:** The ESP32 wakes periodically (or on manual trigger `s`) and calls `POST /device/v1/sync` over TLS. It validates the response signature (`X-Server-Signature`) and loads the new credential into RAM.
4. **Physical Entry:** The user selects resource `A` on the keypad, enters their 6-digit PIN, and presses `#`.
5. **Local Authentication & Unlock:** The terminal validates the HMAC digest locally. If valid, the LCD displays `ACCESS GRANTED`, the SG90 servo sweeps to 180Â° for 3.0 seconds, relocks to 0Â°, and queues an access event to transmit on the next sync heartbeat.

---

## 4. Hardware Requirements & Wiring

### 4.1 Component Inventory
- **ESP32 Development Board:** ESP32-WROOM-32 / NodeMCU-32S (30-pin or 38-pin).
- **Matrix Keypad:** 4Ã—4 tactile or membrane matrix keypad (16 keys).
- **Character LCD:** 16Ã—2 character LCD with PCF8574 IÂ²C backpack.
- **Actuator:** SG90 9g micro-servo motor.
- **Power Supply:** External 5V DC regulated power supply (â‰¥ 1.5A).
- **Prototyping:** Full-size solderless breadboard and jumper wires.

### 4.2 Verified Wiring Table

| ESP32 Pin | Connected Component | Description / Function | Electrical Configuration |
|---|---|---|---|
| **GPIO 19** | Keypad Row 1 | Matrix Row 1 (`1, 2, 3, A`) | `INPUT_PULLUP` (Internal ~45kÎ© pull-up) |
| **GPIO 18** | Keypad Row 2 | Matrix Row 2 (`4, 5, 6, B`) | `INPUT_PULLUP` (Internal ~45kÎ© pull-up) |
| **GPIO 5**  | Keypad Row 3 | Matrix Row 3 (`7, 8, 9, C`) | `INPUT_PULLUP` (Internal ~45kÎ© pull-up) |
| **GPIO 17** | Keypad Row 4 | Matrix Row 4 (`*, 0, #, D`) | `INPUT_PULLUP` (Internal ~45kÎ© pull-up) |
| **GPIO 23** | Keypad Column 1 | Matrix Col 1 (`1, 4, 7, *`) | `OUTPUT` (Actively strobed LOW) |
| **GPIO 22** | Keypad Column 2 | Matrix Col 2 (`2, 5, 8, 0`) | `OUTPUT` (Actively strobed LOW) |
| **GPIO 21** | Keypad Column 3 | Matrix Col 3 (`3, 6, 9, #`) | `OUTPUT` (Actively strobed LOW) |
| **GPIO 16** | Keypad Column 4 | Matrix Col 4 (`A, B, C, D`) | `OUTPUT` (Actively strobed LOW) |
| **GPIO 26** | 16Ã—2 LCD SDA | IÂ²C Serial Data | Open-drain (`Wire.begin(26, 27)`) |
| **GPIO 27** | 16Ã—2 LCD SCL | IÂ²C Serial Clock | Open-drain (`Wire.begin(26, 27)`) |
| **GPIO 13** | SG90 Servo Signal | Orange / Yellow PWM wire | 50 Hz PWM output (`500 Âµs` to `2500 Âµs`) |
| **GND**     | Common Ground Rail | Shared GND | **Must bridge ESP32 GND, Servo GND, and 5V Power Supply GND** |

> [!CAUTION]
> **External Servo Power Rule:** Do **NOT** power the SG90 servo motor directly from the ESP32 3.3V or VIN pins. Servo motor stall and movement currents cause significant voltage drops on the ESP32 regulator, resulting in brownout resets (`Brownout detector was triggered`). Use a dedicated 5V power supply for the servo and tie all grounds together.

---

## 5. Software Requirements & Dependencies

### Runtime & Language Environments
- **Python:** `3.11+`
- **Node.js:** `18.0+` (Tested on Node 20 / 22)
- **Database:** PostgreSQL `14+` (Tested on PostgreSQL 16)
- **Arduino Core:** `esp32` by Espressif Systems (`>= 2.0.14`)

### Backend Python Dependencies (`backend/requirements.txt`)
- `fastapi >= 0.110.0`
- `uvicorn[standard] >= 0.28.0`
- `sqlalchemy >= 2.0.0`
- `alembic >= 1.13.0`
- `psycopg[binary] >= 3.1.0`
- `pydantic-settings >= 2.2.0`
- `pyjwt >= 2.8.0`
- `bcrypt >= 4.1.0`
- `cryptography >= 42.0.0`
- `pytest >= 8.0.0`
- `httpx >= 0.27.0`

### Frontend Node Dependencies (`frontend/package.json`)
- `react: ^19.2.8`
- `react-dom: ^19.2.8`
- `react-router-dom: ^7.18.4`
- `@fontsource/inter: ^5.3.0`
- `lucide-react: ^1.55.0`
- `vite: ^8.3.0`
- `eslint: ^10.10.0`

### Arduino Firmware Libraries
- **`DIYables_LCD_I2C`** by DIYables (`#include <DIYables_LCD_I2C.h>`)
- Core libraries (included with ESP32 board package): `<WiFi.h>`, `<WiFiClientSecure.h>`, `<HTTPClient.h>`, `<Wire.h>`, `<time.h>`, `<sys/time.h>`, `"mbedtls/md.h"`

---

## 6. Repository Structure

```
digital-key-access-control/
â”œâ”€â”€ .env.example                 # Environment variables configuration template
â”œâ”€â”€ .gitignore                   # Version control ignore rules (protects .env, secrets.h)
â”œâ”€â”€ README.md                    # Root project documentation (this document)
â”œâ”€â”€ pytest.ini                   # Pytest test runner configuration
â”œâ”€â”€ render.yaml                  # Render cloud blueprint for backend web service & database
â”œâ”€â”€ backend/
â”‚   â”œâ”€â”€ alembic.ini              # Alembic database migration configuration
â”‚   â”œâ”€â”€ requirements.txt         # Production and development Python dependencies
â”‚   â”œâ”€â”€ alembic/                 # Database schema migrations
â”‚   â”‚   â”œâ”€â”€ env.py               # Migration environment with safety guard
â”‚   â”‚   â””â”€â”€ versions/
â”‚   â”‚       â””â”€â”€ 0001_initial_schema.py # 7 domain tables, partial unique index, trigger
â”‚   â”œâ”€â”€ app/
â”‚   â”‚   â”œâ”€â”€ config.py            # Pydantic Settings loaded from .env
â”‚   â”‚   â”œâ”€â”€ db.py                # SQLAlchemy engine & session factory
â”‚   â”‚   â”œâ”€â”€ deps.py              # Auth verification & device header validation
â”‚   â”‚   â”œâ”€â”€ errors.py            # Custom error handlers and domain exception mapping
â”‚   â”‚   â”œâ”€â”€ main.py              # FastAPI application entry point, CORS, & /health
â”‚   â”‚   â”œâ”€â”€ migration_guard.py   # Safety guard validating migration target hosts
â”‚   â”‚   â”œâ”€â”€ seed.py              # Database seeding logic
â”‚   â”‚   â”œâ”€â”€ models/              # SQLAlchemy 2.0 declarative models
â”‚   â”‚   â”œâ”€â”€ routers/             # API routes (/auth, /resources, /access-requests, /admin, /device/v1)
â”‚   â”‚   â”œâ”€â”€ schemas/             # Pydantic request and response schemas
â”‚   â”‚   â””â”€â”€ services/            # Core domain business logic (credentials, sync, access_requests)
â”‚   â””â”€â”€ scripts/
â”‚       â””â”€â”€ seed.py              # CLI seed runner (`python backend/scripts/seed.py`)
â”œâ”€â”€ docs/
â”‚   â”œâ”€â”€ api-contract.md          # Authoritative REST API specification & Drift Guard
â”‚   â”œâ”€â”€ architecture.md          # In-depth system architecture & Mermaid diagrams
â”‚   â”œâ”€â”€ credential-policy.md     # Authoritative credential lifecycle & crypto test vectors
â”‚   â”œâ”€â”€ hardware-setup.md        # Physical wiring, pin maps, and power safety guide
â”‚   â””â”€â”€ installation.md          # Comprehensive step-by-step development setup guide
â”œâ”€â”€ firmware/
â”‚   â”œâ”€â”€ HARDWARE_NOTES.md        # Physical terminal wiring, pinout, and serial test console
â”‚   â”œâ”€â”€ esp32_sync_terminal.ino  # Production ESP32 firmware (Keypad, LCD, Servo, HTTPS Sync)
â”‚   â”œâ”€â”€ secrets.h                # Local hardware credentials (untracked, Git-ignored)
â”‚   â””â”€â”€ secrets.h.example        # Hardware secrets template
â”œâ”€â”€ frontend/
â”‚   â”œâ”€â”€ index.html               # SPA HTML entry point
â”‚   â”œâ”€â”€ package.json             # Frontend npm dependencies and scripts
â”‚   â”œâ”€â”€ vercel.json              # Vercel SPA routing rewrite rules
â”‚   â”œâ”€â”€ vite.config.js           # Vite build configuration
â”‚   â”œâ”€â”€ eslint.config.js         # ESLint flat configuration
â”‚   â”œâ”€â”€ public/                  # Favicons and SVG assets
â”‚   â”œâ”€â”€ src/                     # React components, pages, design system, and API clients
â”‚   â””â”€â”€ tests/                   # Frontend unit and contract integration tests
â””â”€â”€ tests/                       # Automated backend test suites
    â”œâ”€â”€ integration/             # End-to-end API, admin workflow, and boundary tests
    â””â”€â”€ unit/                    # Fast unit tests for models, sync, auth, and crypto
```

---

## 7. Installation & Setup

For extensive step-by-step setup details, refer to [`docs/installation.md`](file:///d:/Projects/digital-key-access-control/docs/installation.md).

### 7.1 Clone the Repository
```bash
git clone https://github.com/santa0705/digital-key-access-control.git
cd digital-key-access-control
```

### 7.2 Backend Setup
1. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   # Windows PowerShell:
   .venv\Scripts\Activate.ps1
   # Linux/macOS:
   source .venv/bin/activate
   ```
2. **Install dependencies:**
   ```bash
   pip install --upgrade pip
   pip install -r backend/requirements.txt
   ```
3. **Configure `.env`:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` to configure your PostgreSQL `DATABASE_URL` and enable `ALLOW_LOCAL_MIGRATION=true`.
4. **Run migrations and seed default data:**
   ```bash
   alembic -c backend/alembic.ini upgrade head
   python backend/scripts/seed.py
   ```
5. **Start backend server:**
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

### 7.3 Frontend Setup
1. **Install dependencies:**
   ```bash
   cd frontend
   npm install
   ```
2. **Start development server:**
   ```bash
   npm run dev
   ```
   Access the dashboard at `http://localhost:5173`.

### 7.4 ESP32 Firmware Setup
1. Open **Arduino IDE (2.x)**.
2. In **Boards Manager**, install `esp32` by Espressif Systems.
3. In **Library Manager**, install **`DIYables_LCD_I2C`** by DIYables.
4. Copy `firmware/secrets.h.example` to `firmware/secrets.h`:
   ```bash
   cp firmware/secrets.h.example firmware/secrets.h
   ```
5. Fill in your Wi-Fi SSID, password, `DEVICE_API_KEY`, and `PIN_HMAC_KEY`.
6. Connect the ESP32 via USB, select **ESP32 Dev Module** and the active COM port.
7. Open `firmware/esp32_sync_terminal.ino` and click **Upload**.

---

## 8. Configuration & Environment Variables

### Backend Configuration (`.env`)

| Variable Name | Required | Default Example | Purpose & Description |
|---|---|---|---|
| `DATABASE_URL` | **Yes** | `postgresql+psycopg://user:pass@localhost:5432/digital_key` | PostgreSQL database connection string (SQLAlchemy 2 + psycopg 3 driver). |
| `JWT_SECRET` | **Yes** | `replace_with_32_byte_hex_secret` | 32-byte secret used to sign HS256 session tokens for users and administrators. |
| `PIN_HMAC_KEY` | **Yes** | `replace_with_32_byte_hex_hmac_key` | Shared 32-byte hexadecimal key for HMAC-SHA256 digest validation of 6-digit PINs. Must match firmware. |
| `PIN_ENC_KEY` | **Yes** | `replace_with_32_byte_base64_fernet_key` | 32-byte URL-safe base64 Fernet key for symmetric encryption of PINs at rest. Server boot fails if missing. |
| `DEVICE_API_KEY` | **Yes** | `replace_with_32_byte_hex_device_key` | Shared authentication key passed in `X-Device-Key` and used to sign sync response payloads. |
| `CORS_ORIGINS` | **Yes** | `http://localhost:5173` | Comma-separated list of allowed web frontend origins. |
| `ALLOW_LOCAL_MIGRATION` | No | `false` | Migration safety guard: Must be explicitly set to `true` to execute migrations against local databases. |
| `APPROVED_MIGRATION_HOSTS` | No | `localhost,127.0.0.1,::1` | Permitted database hostnames for local migrations. |
| `APPROVED_MIGRATION_PORTS` | No | `5432` | Permitted database ports for local migrations. |
| `APPROVED_MIGRATION_DB_NAMES` | No | `digital_key` | Permitted database names for local migrations. |

### Firmware Configuration (`firmware/secrets.h`)

| Definition | Required | Description |
|---|---|---|
| `WIFI_SSID` | **Yes** | Wi-Fi network SSID for the ESP32 terminal. |
| `WIFI_PASSWORD` | **Yes** | Wi-Fi network WPA2 password. |
| `DEVICE_API_KEY` | **Yes** | 32-byte shared device secret (must match backend `DEVICE_API_KEY`). |
| `PIN_HMAC_KEY` | **Yes** | 32-byte shared HMAC key (must match backend `PIN_HMAC_KEY`). |

---

## 9. Usage Guide

### Terminal & System Startup Sequence
1. Start PostgreSQL and verify connectivity.
2. Launch the FastAPI backend (`uvicorn app.main:app`).
3. Power on the ESP32 terminal (connect USB and external 5V servo supply).
4. **Boot Sequence on LCD:**
   - Displays `Digital Locker | Starting...`
   - Runs self-test vectors 1 & 2 (Serial output confirms HMAC-SHA256 accuracy).
   - Displays `Digital Locker | Connecting WiFi`.
   - Connects to Wi-Fi and queries NTP (`pool.ntp.org`) to synchronize the internal clock.
   - Executes initial synchronization against `https://digital-key-backend-2qvp.onrender.com`.
   - Displays `WiFi connected | Syncing...`.
   - Enters idle state: `Resource: A | Enter PIN: ______`.

### Operating the Physical Terminal
- **Resource Selection:** Press `A` to target Locker A (servo deadbolt latch) or `B` to target Locker B.
- **PIN Entry:** Type the 6-digit numeric PIN. Each digit appears as `*` on the second row of the LCD.
- **Clearing Input:** Press `*` at any time to clear the buffer.
- **Submission:** Press `#` to evaluate the entered code:
  - **Valid Active PIN:** LCD displays `ACCESS GRANTED | Unlocking...`, SG90 servo sweeps to 180Â°, holds for 3.0 seconds, and returns to 0Â° to relock.
  - **Invalid PIN:** LCD displays `ACCESS DENIED | Invalid PIN`. Failed counter increments.
  - **Already Consumed PIN:** LCD displays `PIN REJECTED | Already used`.
  - **Revoked PIN:** LCD displays `PIN REJECTED | Revoked PIN`.
  - **Lockout:** Upon 3 consecutive failed attempts, the LCD displays `ACCESS LOCKED | 30 sec remaining` with a real-time countdown. Keypad input is rejected during lockout.

### Offline Operation
If Wi-Fi drops:
- Cached credentials in terminal RAM remain fully functional.
- Time-bounded validation continues using internal microsecond drift tracking.
- Access telemetry events are saved to the internal queue and automatically uploaded when connectivity resumes.

---

## 10. API Documentation

The backend adheres strictly to the API Contract Specification defined in [`docs/api-contract.md`](file:///d:/Projects/digital-key-access-control/docs/api-contract.md).

### Core Endpoints

| Method | Endpoint | Auth | Purpose |
|---|---|---|---|
| `GET` | `/health` | None | Operational probe returning database state and UTC `server_time`. |
| `POST` | `/auth/login` | None | Authenticates user/admin; returns Bearer JWT token. |
| `GET` | `/resources` | None | Lists resources with occupancy, active keys, and latch states. |
| `POST` | `/access-requests` | Bearer | Submits an access reservation request for a specific resource and time window. |
| `GET` | `/access-requests/me` | Bearer | Lists requests submitted by the authenticated user. |
| `GET` | `/access-requests/{id}/pin` | Bearer | Reveals decrypted 6-digit PIN to the authorized request owner. |
| `GET` | `/admin/access-requests` | Admin | Lists pending and historical access requests with status filtering. |
| `POST` | `/admin/access-requests/{id}/approve` | Admin | Approves request, issues cryptographic credential, and increments `change_seq`. |
| `POST` | `/admin/access-requests/{id}/reject` | Admin | Rejects pending access request with rejection reason. |
| `POST` | `/admin/credentials/{id}/revoke` | Admin | Immediately revokes an active credential with `revoke_reason`. |
| `GET` | `/admin/logs` | Admin | Queries unified access and audit log stream (`server` and `device` events). |
| `GET` | `/admin/nodes` | Admin | Lists terminal hardware nodes with heartbeat and clock synchronization state. |
| `POST` | `/device/v1/sync` | Device Key | Hardware synchronization: ingests telemetry events, returns credential deltas. |

---

## 11. Security Design & Cryptography

1. **Hardware Cryptographic Verification (Test Vector 1):**
   On every cold boot, the ESP32 firmware executes a self-test calculating HMAC-SHA256 against official test vector values (`docs/credential-policy.md Â§2.3`). If verification fails, the device halts execution.
2. **Mutual Response Signing (Test Vector 2):**
   The backend signs all `/device/v1/sync` response bodies using `DEVICE_API_KEY`. The ESP32 re-computes and compares the HMAC in `X-Server-Signature` before accepting any credential deltas into RAM.
3. **Replay & Timestamp Protection:**
   Sync payloads require an unpredictable 16-hex client nonce and `X-Device-Timestamp`. The backend rejects requests with timestamps skewed beyond 45 seconds (`ONLINE_WINDOW_S`).
4. **Reversible Storage Protection:**
   The database contains only `pin_hmac` and `pin_encrypted` (Fernet symmetric ciphertext). Plaintext PINs are never persisted in databases, logs, terminal flash, or browser storage.
5. **Fail-Closed Clock Verification:**
   The ESP32 firmware marks time as `untrusted` until anchored by NTP or a verified backend response. Expired credentials cannot be used even if network connectivity is severed.

---

## 12. Testing & Troubleshooting

### Available Automated Test Suites

**1. Frontend Tests:**
```bash
cd frontend
npm test
```
*Result: 25 unit and contract integration tests pass (Date utilities in Asia/Kolkata IST and API client contract mapping).*

**2. Frontend Linter & Production Build:**
```bash
cd frontend
npm run lint
npm run build
```
*Result: ESLint flat config passes with 0 errors; Vite compiles production bundle in `< 1.0s`.*

**3. Backend Tests:**
```bash
.venv\Scripts\python -m pytest tests/unit/test_contract_paths.py tests/unit/test_device_sync.py
```
*Result: All contract path guard tests and device synchronization unit tests pass.*

### Common Troubleshooting Scenarios

| Symptom | Root Cause | Solution |
|---|---|---|
| **LCD displays black boxes or blank** | Contrast potentiometer on IÂ²C backpack misadjusted. | Turn the small blue screw on the PCF8574 backpack with a screwdriver until characters appear sharp. |
| **Compilation error: `DIYables_LCD_I2C.h: No such file`** | Missing library in Arduino IDE. | Open Library Manager (Ctrl+Shift+I), search for `DIYables_LCD_I2C`, and click Install. |
| **ESP32 reboots continuously during servo sweep** | Servo powered from ESP32 regulator causing brownout. | Disconnect servo 5V from ESP32. Connect to external 5V power supply. Bridge external GND with ESP32 GND. |
| **`[SYNC] ERROR: http.begin failed`** | Incorrect Wi-Fi credentials or backend URL unreachable. | Verify SSID/password in `secrets.h`. Confirm Render backend URL is accessible via browser. |
| **`[SECURITY] X-Server-Signature MISMATCH`** | `DEVICE_API_KEY` in `secrets.h` does not match backend `.env`. | Ensure the exact same 32-byte hexadecimal string is configured in both files. |
| **Database migration blocked by safety guard** | `ALLOW_LOCAL_MIGRATION` is `false`. | Set `ALLOW_LOCAL_MIGRATION=true` in `.env` for your local development database. |

---

## 13. Deployment Architecture

- **Backend:** Deployed as a Python web service on **Render** running `uvicorn app.main:app` with automated database migrations (`AUTO_MIGRATE=true`) and live health monitoring at `/health`.
- **Database:** Managed **PostgreSQL** instance on Neon / Render with pooled SSL connections.
- **Frontend:** Hosted on **Vercel** with global CDN distribution and SPA URL rewrites via `vercel.json`.
- **Hardware Terminal:** Pre-flashed with production Render URL (`https://digital-key-backend-2qvp.onrender.com`) and Google Trust Services Root R4 certificate.

---

## 14. Limitations & Future Roadmap

- **Prototype Enclosure:** The current physical setup is evaluated on a modular test rig. Future revisions will feature a custom 3D-printed or sheet-metal enclosure with internal wire routing.
- **Network Dependency for Initial Anchor:** The terminal requires an initial internet connection at boot to acquire trusted time via NTP before authenticating time-bounded keys. Future hardware revisions will incorporate a battery-backed RTC.
- **Advance Booking Engine:** Current implementation enforces Rule R1 (one active key per resource). A future release will introduce an advance calendar reservation engine.

---

## 15. Contributors & Acknowledgements

- **Repository:** [`santa0705/digital-key-access-control`](https://github.com/santa0705/digital-key-access-control)
- **Contributors:** Person A (Domain Models, Database Schema, Access Request Services, Management UI) & Person B (Authentication, Security Policies, Admin Operations, Device Synchronization Protocol, ESP32 Firmware).

---

## 16. License

The licensing terms for this repository have not yet been formally specified. All rights are reserved by the original repository authors. Open-source redistribution or commercial licensing will be finalized prior to public distribution.
