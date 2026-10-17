# Digital Key-Based Secure Access Control — API Contract Specification

> **Document Status:** `contracts-v1 FINAL SPECIFICATION`<br>
> **Milestone:** Step 2 Sign-Off / `contracts-v1`<br>
> **Authors & Stakeholders:** Person A (Models, Schema, User Services & UI) & Person B (Auth, Admin, Device Sync, Core Backend)

---

## 1. Decisions at Sign-Off (contracts-v1)

The following decisions have been agreed upon by Person A and Person B to establish the authoritative contract baseline for `contracts-v1`:

| Ref | Settled Decision / Specification | Status | Architectural Rationale & Implementation Ownership |
|---|---|---|---|
| **C1** | `/access-requests` replaces legacy `/bookings`. | `AGREED` | Clarifies physical shared resource reservation semantics. |
| **C2** | Integer 64-bit IDs (`bigint`); strict ISO-8601 UTC `Z` timestamps (seconds precision, no fractional seconds); lowercase `snake_case` enums; single global error envelope. | `AGREED` | Ensures uniform serialization across Python, JavaScript, and ESP32 C++. |
| **C3** | SQLAlchemy 2.x + Alembic + psycopg 3 backend; React + JSX frontend. | `AGREED` | Async-ready relational stack, eliminates TypeScript build overhead for rapid student MVP. |
| **C4** | PIN verification via keyed HMAC-SHA256 (`<resource_code>:<pin>`); secure reveal via Fernet symmetric encryption. | `AGREED` | Prevents plaintext PIN storage while permitting repeatable owner retrieval. |
| **C5** | One active credential per resource (Rule R1). Advance booking calendar deferred to post-MVP. Replacement requires explicit `replace_existing: true` with UI confirmation. | `AGREED` | Eliminates concurrent conflicting unlock codes on single physical latch. Protects active users from accidental revocation. |
| **C6** | One-row `sync_state` table with atomic counter (`next_change_seq()`) replaces free-running PostgreSQL sequences. | `AGREED` | Guarantees strictly gap-free, monotonic change sequences without out-of-order commit skips. |
| **C7** | Device sync acknowledged solely by device's subsequent request (`last_seq`). Server never marks records "applied" on its own response. | `AGREED` | Protects against message loss over unstable Wi-Fi. |
| **C8** | `nodes.time_state` tracks clock status (`untrusted`, `rtc_validated`, `server_anchored`). Baseline is Tier 3 `server_anchored`. Default window `TIME_ANCHOR_MAX_AGE_S = 90` seconds (configurable). | `AGREED` | Fail-closed security: terminal rejects entries if server time anchor expires. 90 seconds tolerates brief Wi-Fi jitter while bounding revocation delay. |
| **C9** | Unified `access_events` table for both device telemetry and server audit logs (`source = 'device' \| 'server'`). | `AGREED` | Single chronologically ordered audit log. |
| **C10** | Work division: Auth/Admin/Sync to Person B; Resources/User Request pages/Mock device client to Person A. | `AGREED` | Minimizes Git merge conflicts across files. |
| **C11** | `access_requests.status` includes `revoked`; `credentials` includes `revoke_reason` (`admin` or `superseded`). | `AGREED` | Distinguishes manual administrator revocations from replacement supersessions. |
| **C12** | `GET /health` is an uncounted operational health probe, outside the 12 core contract endpoints. | `AGREED` | Used by healthcheck monitors, phone testing, and deploy validation. |
| **C13** | Tier 4 DS1307/HW-111 RTC integration **DISABLED** for the sprint. | `AGREED` | Safety block: HW-111 operates at 5V with dangerous charging circuit on CR2025 non-rechargeable cells. Blocked until multimeter & hardware gates G4/G5 pass. |
| **C14** | Authenticated device sync responses via `X-Server-Signature` (HMAC-SHA256) and request replay protection via `request_nonce` and `X-Device-Timestamp`. | `AGREED` | Person B signs responses in `services/sync.py`; Person A verifies in ESP32 `sync_client`. Prevents rogue LAN actors from forging fake ACKs. |
| **C15** | Durable handling of stale-epoch events (`credential_id = NULL`, `note = "unknown_credential"`). | `AGREED` | Prevents foreign key crashes and infinite sync retry loops after database resets. ACKs only sent after durable commit. |
| **G1** | Add `revoke_reason` (`null`, `admin`, `superseded`) to credential response object. | `AGREED` | Informs frontend why an active credential was invalidated. |
| **G6** | Deterministic validation sequence and RAM-only 3-failure / 30s lockout. | `AGREED` | Protects NVS flash memory from write wear. Reset bypass acknowledged as prototype trade-off. |
| **G7** | Domain services raise standardized domain exceptions; `errors.py` maps them into standard HTTP status codes. | `AGREED` | Routers never manually construct error JSON dictionaries. |

---

## 2. Path Drift Guard List

The following fenced block defines the authoritative list of 12 contract endpoints plus `/health`. Automated test `tests/unit/test_contract_paths.py` reads this block directly to prevent API drift:

```text
/auth/login
/resources
/access-requests
/access-requests/me
/access-requests/{id}/pin
/admin/access-requests
/admin/access-requests/{id}/approve
/admin/access-requests/{id}/reject
/admin/credentials/{id}/revoke
/admin/logs
/admin/nodes
/device/v1/sync
/health
```

---

## 3. Global Conventions, Error Format & Security Headers

### 3.1 Identifiers & Formats
- **Entity IDs:** Positive 64-bit integers (`bigint`), e.g., `1`, `42`.
- **String IDs:**
  - `resource.code`: Uppercase single character (`A`, `B`).
  - `node_code`: Lowercase alphanumeric identifier (`node-01`).
  - `epoch`: UUIDv4 string generated on database initialization or reset.
  - `event_id`: Unique identifier formatted as `node-01-<6-digit-nvs-counter>-<8-hex-random>` for device events, or `srv-<8-hex-random>` for server events.
  - `request_nonce`: 16-character lowercase hexadecimal random string generated per sync request.
- **Timestamps:** Strict ISO-8601 UTC with seconds precision and literal uppercase `Z` suffix (`YYYY-MM-DDTHH:MM:SSZ`).
  - Timestamps with fractional seconds (`.123456`) or non-`Z` timezone offsets (`+00:00`, `+05:30`) are rejected with `422 validation_error`.

### 3.2 Standard Error Envelope
All error responses across all routes (including FastAPI request validation errors) must strictly adhere to the following JSON envelope:

```json
{
  "error": {
    "code": "invalid_state",
    "message": "Request 5 is already approved; only pending requests can be approved."
  }
}
```

*Implementation Note:* FastAPI's default `RequestValidationError` (which outputs `{"detail": [...]}`) is intercepted in `backend/app/errors.py` by a custom exception handler that flattens validation issues into this standard envelope (`code: "validation_error"`).

### 3.3 Standard Error Codes & HTTP Status Mapping

| HTTP Status | Error Code (`code`) | Trigger Condition |
|---|---|---|
| `401 Unauthorized` | `unauthorized` | Missing, malformed, or expired JWT bearer token. |
| `401 Unauthorized` | `invalid_credentials` | Incorrect user email or password. |
| `401 Unauthorized` | `invalid_device_key` | Missing or invalid `X-Device-Key` header on device routes. |
| `401 Unauthorized` | `invalid_device_timestamp`| Device request timestamp deviates by > 30 s from server UTC time. |
| `403 Forbidden` | `forbidden` | Authenticated user lacks permission (e.g. non-admin accessing `/admin/*`, or admin/other user accessing `/access-requests/{id}/pin`). |
| `404 Not Found` | `not_found` | Requested entity ID does not exist. |
| `404 Not Found` | `resource_not_found` | Resource ID in access request does not exist. |
| `404 Not Found` | `unknown_node` | Terminal `node_code` unrecognized by server. |
| `409 Conflict` | `invalid_state` | Entity lifecycle state prohibits the operation (e.g. approving a non-pending request, revoking already terminal credential). |
| `409 Conflict` | `active_credential_exists` | Resource already has an active credential (Rule R1) and `replace_existing` was false or omitted. |
| `409 Conflict` | `window_expired` | Access request validity window has already passed (`end_at <= now`). |
| `409 Conflict` | `pin_unavailable` | Requested PIN is not active (request pending, rejected, consumed, expired, or revoked). |
| `422 Unprocessable` | `validation_error` | Request payload fails schema validation, invalid date order (`end_at <= start_at`), duration > 24 h, start > 1 min in past, or missing `Z` offset. |
| `503 Service Unavailable`| `sync_state_inconsistent`| Database `sync_state.current_seq` is less than `max(credentials.change_seq)`. |

### 3.4 Security Headers & Cache Controls
- **PIN Reveal (`GET /access-requests/{id}/pin`):** Must return `Cache-Control: no-store, private` and `Pragma: no-cache` to prevent browser or proxy caching of plain PINs.
- **CORS:** Controlled by `CORS_ORIGINS` in `.env`. Restricted to frontend development URL (`http://localhost:5173`) and designated LAN demo origins.

---

## 4. Shared Domain Data Structures

### 4.1 Shared `AccessRequest` Object
Used consistently across user and admin endpoints:

```json
{
  "id": 5,
  "resource": {
    "id": 1,
    "code": "A",
    "name": "Locker A",
    "kind": "physical"
  },
  "user": {
    "id": 2,
    "full_name": "Demo User"
  },
  "start_at": "2026-10-12T09:00:00Z",
  "end_at": "2026-10-12T10:00:00Z",
  "purpose": "Collect sensor testing kit",
  "status": "approved",
  "decision_note": "Approved for bench test",
  "decided_at": "2026-10-11T14:02:11Z",
  "created_at": "2026-10-11T13:40:05Z",
  "credential": {
    "id": 7,
    "status": "active",
    "valid_from": "2026-10-12T09:00:00Z",
    "valid_until": "2026-10-12T10:00:00Z",
    "revoke_reason": null
  }
}
```
*Rules:*
- When `status` is `pending` or `rejected`, `credential`, `decision_note`, and `decided_at` are `null`.
- When `credential.status` is `revoked`, `revoke_reason` is `"admin"` or `"superseded"`.
- Plaintext PIN is **never** included in this shape.

---

## 5. Contract Endpoints Specification

### 5.1 Authentication (`/auth`)

#### `POST /auth/login`
- **Ownership:** Person B
- **Auth:** Public
- **Purpose:** Authenticate user or admin using email and password; returns JWT session token (HS256, 8-hour lifetime).

**Request Body:**
```json
{
  "email": "user@demo.local",
  "password": "demo-password"
}
```

**Success Response (`200 OK`):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 28800,
  "user": {
    "id": 2,
    "email": "user@demo.local",
    "full_name": "Demo User",
    "role": "user"
  }
}
```

**Errors:**
- `401 Unauthorized` (`invalid_credentials`): Incorrect email or password.
- `422 Unprocessable Entity` (`validation_error`): Invalid email format or missing fields.

---

### 5.2 User Resources & Access Requests (`/resources`, `/access-requests`)

#### `GET /resources`
- **Ownership:** Person A
- **Auth:** Bearer Token (`user` or `admin`)
- **Purpose:** List all active physical or simulated locker resources.

**Success Response (`200 OK`):**
```json
[
  {
    "id": 1,
    "code": "A",
    "name": "Locker A",
    "kind": "physical",
    "is_active": true
  },
  {
    "id": 2,
    "code": "B",
    "name": "Locker B",
    "kind": "simulated",
    "is_active": true
  }
]
```

---

#### `POST /access-requests`
- **Ownership:** Person A
- **Auth:** Bearer Token (`user` or `admin`)
- **Purpose:** Submit a new request for access to a resource for a specified UTC window.

**Request Body:**
```json
{
  "resource_id": 1,
  "start_at": "2026-10-12T09:00:00Z",
  "end_at": "2026-10-12T10:00:00Z",
  "purpose": "Collect kit"
}
```

**Success Response (`201 Created`):**
Returns created `AccessRequest` object with `status: "pending"` and `credential: null`.

**Validation Rules & Errors:**
- `end_at > start_at`, duration ≤ 24 h.
- `start_at` cannot be more than 1 minute in the past relative to server UTC.
- Missing timezone `Z` returns `422 validation_error`.
- Unknown `resource_id` returns `404 resource_not_found`.

---

#### `GET /access-requests/me`
- **Ownership:** Person A
- **Auth:** Bearer Token (`user`)
- **Purpose:** List all access requests submitted by the calling user, newest first.

**Success Response (`200 OK`):**
Returns array of `AccessRequest` objects (`[]` when none).

---

#### `GET /access-requests/{id}/pin`
- **Ownership:** Person A (invokes Person B's `reveal_pin` service)
- **Auth:** Bearer Token (**Requester owner only**. Admins and other users receive `403 forbidden`).
- **Headers Returned:** `Cache-Control: no-store, private`, `Pragma: no-cache`
- **Purpose:** Reveal the decrypted 6-digit PIN while the credential is in `active` status. Audit event `pin_revealed` is recorded atomically. Repeatable for owner while active.

**Success Response (`200 OK`):**
```json
{
  "request_id": 5,
  "resource_code": "A",
  "pin": "482916",
  "valid_from": "2026-10-12T09:00:00Z",
  "valid_until": "2026-10-12T10:00:00Z"
}
```

**Errors:**
- `403 Forbidden` (`forbidden`): Caller is not the creator of the request (including admins).
- `404 Not Found` (`not_found`): Request ID does not exist.
- `409 Conflict` (`pin_unavailable`): Request is not approved, or credential is terminal (`consumed`, `expired`, `revoked`).

---

### 5.3 Admin Operations (`/admin`)

#### `GET /admin/access-requests?status={pending|approved|rejected|revoked|all}`
- **Ownership:** Person B
- **Auth:** Bearer Token (`admin` only)
- **Purpose:** List access requests filtered by status (defaults to `pending`). Approved rows contain credential summary.

**Success Response (`200 OK`):**
Returns array of `AccessRequest` objects.

---

#### `POST /admin/access-requests/{id}/approve`
- **Ownership:** Person B
- **Auth:** Bearer Token (`admin` only)
- **Purpose:** Atomically approve request and generate active credential. Enforces Rule R1.

**Request Body:**
```json
{
  "note": "Approved for lab session",
  "replace_existing": false
}
```

**Success Response (`200 OK`):**
Returns updated `AccessRequest` with `status: "approved"` and embedded `credential`. Plaintext PIN is **never** returned.

**Conflict Scenario (`409 Conflict` — `active_credential_exists`):**
Triggered if an active credential already exists for this resource and `replace_existing` is `false`:
```json
{
  "error": {
    "code": "active_credential_exists",
    "message": "Resource A has active credential 6 (request 4). Revoke it or approve with replace_existing."
  }
}
```

**Replacement Scenario (`replace_existing: true`):**
When confirmed by the admin, the existing active credential is atomically marked `status: "revoked"` (`revoke_reason: "superseded"`), its parent request is set to `status: "revoked"`, and the new credential is created in the same transaction. Both row updates advance `next_change_seq()`. The UI requires a prominent confirmation modal warning before submission.

---

#### `POST /admin/access-requests/{id}/reject`
- **Ownership:** Person B
- **Auth:** Bearer Token (`admin` only)
- **Purpose:** Reject a pending access request. No credential or sequence counter is generated.

**Request Body:**
```json
{
  "note": "Locker unavailable during maintenance"
}
```

**Success Response (`200 OK`):**
Returns updated `AccessRequest` with `status: "rejected"`.

---

#### `POST /admin/credentials/{id}/revoke`
- **Ownership:** Person B
- **Auth:** Bearer Token (`admin` only)
- **Purpose:** Manually revoke an active credential. Takes effect on device at next sync.

**Request Body:**
```json
{
  "note": "Key reported compromised"
}
```

**Success Response (`200 OK`):**
```json
{
  "id": 7,
  "status": "revoked",
  "revoke_reason": "admin",
  "revoked_at": "2026-10-12T09:20:00Z",
  "change_seq": 45
}
```

**Errors:**
- `409 Conflict` (`invalid_state`): Credential is already terminal (`consumed`, `expired`, `revoked`).

---

#### `GET /admin/logs?limit=100&source=all`
- **Ownership:** Person B
- **Auth:** Bearer Token (`admin` only)
- **Purpose:** Paginated audit log containing both terminal events and server operations, sorted newest first.
- **Parameters:** `limit` (integer, 1–500, default 100), `source` (`all` | `device` | `server`, default `all`).

**Success Response (`200 OK`):**
```json
[
  {
    "id": 31,
    "source": "device",
    "event_id": "node-01-000123-a1b2c3d4",
    "event_type": "pin_rejected",
    "reason": "wrong_pin",
    "resource_code": "A",
    "request_id": null,
    "credential_id": null,
    "actor": "node-01",
    "note": null,
    "device_time": "2026-10-12T09:14:58Z",
    "time_trusted": true,
    "occurred_at": "2026-10-12T09:15:02Z"
  },
  {
    "id": 30,
    "source": "server",
    "event_id": "srv-0b9d7c52",
    "event_type": "credential_issued",
    "reason": null,
    "resource_code": "A",
    "request_id": 5,
    "credential_id": 7,
    "actor": "admin@demo.local",
    "note": null,
    "device_time": null,
    "time_trusted": null,
    "occurred_at": "2026-10-11T14:02:11Z"
  }
]
```

---

#### `GET /admin/nodes`
- **Ownership:** Person B
- **Auth:** Bearer Token (`admin` only)
- **Purpose:** Retrieve connectivity and status of registered access terminal nodes.

**Success Response (`200 OK`):**
```json
[
  {
    "id": 1,
    "node_code": "node-01",
    "firmware_version": "0.1.0",
    "last_seen_at": "2026-10-12T09:15:02Z",
    "online": true,
    "time_state": "server_anchored",
    "last_acked_seq": 44,
    "server_seq": 44
  }
]
```
*(Node is evaluated as `online: true` if `last_seen_at` is within the last 45 seconds).*

---

### 5.4 Device Synchronization Protocol (`/device/v1`)

#### `POST /device/v1/sync`
- **Ownership:** Person B (server implementation), Person A (ESP32 client implementation)
- **Request Headers:**
  - `X-Device-Key: <DEVICE_API_KEY>` (evaluated in constant time)
  - `X-Device-Timestamp: <ISO-8601 UTC Z>` (server checks $| \text{timestamp} - \text{server\\_time} | \le 30\text{ s}$; returns `401 invalid_device_timestamp` if skew exceeds 30s)
- **Response Headers:**
  - `X-Server-Signature: <64-character lowercase hex digest>`
- **Response Authentication & Request Binding Protocol:**
  1. The device generates a random 16-character hex `request_nonce` for each sync request.
  2. The server echoes this exact `request_nonce` inside the JSON response payload.
  3. The server signs the raw UTF-8 bytes of the HTTP response body:
     $$\text{X-Server-Signature} = \text{hex}(\text{HMAC-SHA256}(\text{DEVICE\\_API\\_KEY.encode('utf-8')}, \text{response\\_body\\_bytes}))$$
  4. The ESP32 buffers the response and verifies `X-Server-Signature` using mbedTLS.
  5. The ESP32 asserts that `response.request_nonce == request.request_nonce`.
  6. **Critical Failure Rule:** If `X-Server-Signature` fails or `request_nonce` does not match, the ESP32 must discard the entire response immediately:
     - No credentials are saved or modified in NVS.
     - `last_seq` is NOT advanced.
     - Event queue in NVS is NOT cleared or updated.
     - Device clock anchor is NOT updated.

**Request Payload:**
```json
{
  "node_code": "node-01",
  "firmware_version": "0.1.0",
  "epoch": "3f6c1d0e-8a52-4b7e-9c1f-52d1a0b7e411",
  "last_seq": 42,
  "request_nonce": "c4b8e21a8f9042b7",
  "time_state": "server_anchored",
  "device_time": "2026-10-12T09:15:02Z",
  "events": [
    {
      "event_id": "node-01-000123-a1b2c3d4",
      "event_type": "pin_rejected",
      "reason": "wrong_pin",
      "resource_code": "A",
      "credential_id": null,
      "device_time": "2026-10-12T09:14:58Z",
      "time_trusted": true
    },
    {
      "event_id": "node-01-000124-5e0f77a1",
      "event_type": "credential_accepted",
      "reason": null,
      "resource_code": "A",
      "credential_id": 6,
      "device_time": "2026-10-12T09:15:00Z",
      "time_trusted": true
    }
  ]
}
```

**Success Response (Delta Mode):**
```json
{
  "server_time": "2026-10-12T09:15:02Z",
  "epoch": "3f6c1d0e-8a52-4b7e-9c1f-52d1a0b7e411",
  "request_nonce": "c4b8e21a8f9042b7",
  "full_resync": false,
  "from_seq": 42,
  "to_seq": 44,
  "server_seq": 44,
  "has_more": false,
  "credentials": [
    {
      "id": 6,
      "change_seq": 43,
      "resource_code": "A",
      "status": "revoked",
      "valid_from": "2026-10-12T09:00:00Z",
      "valid_until": "2026-10-12T10:00:00Z",
      "pin_hmac": "5722b9d3d2b7debfdd32d993ceb2cb748a88eb72d0d69b0157d19eb932ad8019"
    },
    {
      "id": 7,
      "change_seq": 44,
      "resource_code": "A",
      "status": "active",
      "valid_from": "2026-10-12T09:00:00Z",
      "valid_until": "2026-10-12T10:00:00Z",
      "pin_hmac": "e48f878502a47172ea00cf018627956dab95a5073357dc5b01220bc4179093bc"
    }
  ],
  "acked_event_ids": [
    "node-01-000123-a1b2c3d4",
    "node-01-000124-5e0f77a1"
  ]
}
```

**Durable Ingestion & Stale Epoch Handling Rules:**
1. Event insertion executes `INSERT INTO access_events ... ON CONFLICT (event_id) DO NOTHING`.
2. If an event carries a `credential_id` that does not exist in the database (e.g. from a prior database epoch before a reset), the event is inserted with `credential_id = NULL` and `note = "unknown_credential"`. Foreign key violation is avoided.
3. An `event_id` is included in `acked_event_ids` **only after the write transaction commits to the database**. Uncommitted events are never acknowledged.

---

### 5.5 Operational Health Probe

#### `GET /health`
- **Ownership:** Person B
- **Auth:** Public
- **Purpose:** Operational liveness probe and database connectivity check. Executes `SELECT 1` against the PostgreSQL connection pool.

**Success Response (`200 OK`):**
```json
{
  "status": "ok",
  "server_time": "2026-10-12T09:00:00Z",
  "database": "connected"
}
```

---

## 6. Open Decisions for Joint Sign-Off

All major contract ambiguities have been settled for `contracts-v1`. The single configurable operational parameter is:
- **`TIME_ANCHOR_MAX_AGE_S`:** Default is settled at **90 seconds** (`90` in code and config). The deployment environment may tune this between 60s and 120s based on local Wi-Fi stability without violating the API contract.
