# Installation & Development Environment Setup Guide

This guide provides end-to-end instructions for setting up the local development environment for the **Digital Key-Based Secure Access Control** system across all three tiers: FastAPI Backend, React Frontend, and ESP32 Firmware.

---

## 1. System Prerequisites

Ensure the following tools are installed on your host system:

| Tool | Minimum Version | Verified Version | Purpose |
|---|---|---|---|
| **Python** | 3.10+ | 3.11.9 | Backend API, migrations, and test runner. |
| **Node.js** | 18.0+ | 20.x / 22.x | Frontend build toolchain and test runner. |
| **npm** | 9.0+ | 10.x | Frontend package manager. |
| **PostgreSQL** | 14.0+ | 16.x | Primary relational database. |
| **Arduino IDE** | 2.0+ | 2.3+ | Firmware editing, compilation, and flashing. |
| **Git** | 2.30+ | 2.40+ | Version control. |

---

## 2. Repository Setup

Clone the repository and inspect the directory structure:

```bash
git clone https://github.com/santa0705/digital-key-access-control.git
cd digital-key-access-control
```

---

## 3. Backend Setup (FastAPI & PostgreSQL)

### 3.1 Create and Activate Virtual Environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3.2 Install Python Dependencies
```bash
pip install --upgrade pip
pip install -r backend/requirements.txt
```

### 3.3 Configure Environment Variables
Copy the root `.env.example` template to `.env`:

```bash
cp .env.example .env
```

Open `.env` and fill in the required keys:

```ini
# Database connection string (SQLAlchemy 2 + psycopg 3)
DATABASE_URL=postgresql+psycopg://digital_key_user:your_db_password_here@localhost:5432/digital_key

# Migration Safety Guard: set to true for local development databases
ALLOW_LOCAL_MIGRATION=true
APPROVED_MIGRATION_HOSTS=localhost,127.0.0.1,::1
APPROVED_MIGRATION_PORTS=5432
APPROVED_MIGRATION_DB_NAMES=digital_key
APPROVED_MIGRATION_USERS=

# Cryptographic Keys (matching .env.example placeholders)
JWT_SECRET=replace_with_generated_jwt_secret_hex_32_bytes
PIN_HMAC_KEY=replace_with_generated_hmac_key_hex_32_bytes
PIN_ENC_KEY=replace_with_generated_fernet_key_base64_32_bytes
DEVICE_API_KEY=replace_with_generated_device_api_key

# CORS allowed frontend origin
CORS_ORIGINS=http://localhost:5173
```

> [!TIP]
> Generate a fresh 32-byte Fernet encryption key (`PIN_ENC_KEY`) using Python:
> ```bash
> python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
> ```

### 3.4 Create PostgreSQL Database & Run Migrations

1. Create the database in your local PostgreSQL instance:
   ```sql
   CREATE DATABASE digital_key;
   ```
2. Execute the Alembic database migration to generate all tables, partial unique indexes, triggers, and sequences:
   ```bash
   alembic -c backend/alembic.ini upgrade head
   ```
3. Seed default demo data (administrator user `admin@demo.local`, demo resources A & B, terminal node `node-01`):
   ```bash
   python backend/scripts/seed.py
   ```

### 3.5 Run the Backend Development Server
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Verify backend health by opening your browser or running:
```bash
curl http://localhost:8000/health
```
Expected response:
```json
{"status":"ok","server_time":"2026-10-16T15:30:00Z","database":"connected"}
```

Interactive OpenAPI documentation is accessible at `http://localhost:8000/docs`.

---

## 4. Frontend Setup (React + Vite)

### 4.1 Install Node Dependencies
```bash
cd frontend
npm install
```

### 4.2 Configure Frontend Environment
By default, the frontend connects to `http://localhost:8000`. If you wish to customize the target backend, copy `frontend/.env.example` to `frontend/.env`:

```ini
VITE_API_BASE_URL=http://localhost:8000
```

### 4.3 Run Frontend Development Server
```bash
npm run dev
```
The application will launch on `http://localhost:5173`.

### 4.4 Run Frontend Verification
Run frontend tests and production bundle build:
```bash
npm test
npm run build
```

---

## 5. ESP32 Firmware Setup (Arduino IDE)

### 5.1 Configure Arduino IDE for ESP32
1. Open **Arduino IDE** (version 2.x recommended).
2. Go to **File → Preferences**.
3. In **Additional boards manager URLs**, add:
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
4. Open **Tools → Board → Boards Manager**, search for `esp32` by Espressif Systems, and click **Install** (version 2.0.14 or 3.x).

### 5.2 Install Required Libraries
Open **Tools → Manage Libraries** (Ctrl+Shift+I) and install:
- **`DIYables_LCD_I2C`** by DIYables (exact library required for 16×2 character LCD over I²C).

*(Note: Matrix keypad scanning is implemented using pure GPIO register manipulation with internal pull-ups; no external keypad library is required).*

### 5.3 Configure Terminal Secrets
1. Navigate to the `firmware/` directory.
2. Copy `firmware/secrets.h.example` to `firmware/secrets.h`:
   ```bash
   cp firmware/secrets.h.example firmware/secrets.h
   ```
3. Open `firmware/secrets.h` and configure your credentials:
   ```cpp
   #ifndef SECRETS_H
   #define SECRETS_H

   // Your local Wi-Fi Hotspot / Router credentials
   #define WIFI_SSID "Your_WiFi_SSID"
   #define WIFI_PASSWORD "Your_WiFi_Password"

   // Must match DEVICE_API_KEY and PIN_HMAC_KEY in your backend .env
   #define DEVICE_API_KEY "replace_with_device_api_key_from_env"
   #define PIN_HMAC_KEY "replace_with_pin_hmac_key_from_env"

   #endif
   ```

### 5.4 Board & Port Settings
Under the **Tools** menu in Arduino IDE, select:
- **Board:** `ESP32 Dev Module`
- **CPU Frequency:** `240MHz (WiFi/BT)`
- **Flash Frequency:** `80MHz`
- **Upload Speed:** `921600` (or `115200` if cable stability requires)
- **Port:** Select your USB serial COM port (e.g. `COM5` on Windows, `/dev/ttyUSB0` on Linux)

### 5.5 Upload Firmware
1. Open `firmware/esp32_sync_terminal.ino`.
2. Click the **Upload** button (arrow icon).
3. If the console displays `Connecting......_____`, hold down the **BOOT** button on the ESP32 board for two seconds until the upload starts.
4. Once flashed, open the Serial Monitor at **115200 baud** to observe boot diagnostics.
