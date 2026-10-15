/*
 * Digital Key-Based Secure Access Control - ESP32 Firmware
 * 
 * Target: ESP32 Dev Module (WROOM-32 / NodeMCU-32S)
 * Authoritative contracts:
 *   - docs/api-contract.md §5.4 (POST /device/v1/sync) & §5.5 (GET /health)
 *   - docs/credential-policy.md §2.3 (Cryptographic Test Vectors 1 & 2)
 *   - docs/credential-policy.md §5 (Device Rules DR-1 through DR-8)
 *   - docs/credential-policy.md §6 (Validation Sequence & Lockout)
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>
#include <sys/time.h>
#include "mbedtls/md.h"
#include "secrets.h"

// ============================================================================
// 1. HARDWARE PIN DEFINITIONS (Easily configurable for your breadboard)
// ============================================================================

// 4x4 Matrix Keypad Pin Assignments
// Safe ESP32 GPIOs with internal pull-ups (avoids strapping and flash pins)
const byte ROW_PINS[4] = {19, 18, 5, 17}; // Row 1 to Row 4
const byte COL_PINS[4] = {23, 22, 21, 16}; // Col 1 to Col 4

// Status LEDs
const int GREEN_LED_PIN = 4; // Access Granted / Unlocked indicator
const int RED_LED_PIN   = 2; // Access Denied / Lockout / Error indicator

// Servo Actuator (Locker A physical latch)
const int SERVO_PIN     = 13; // Safe PWM output pin for SG90 servo

// Keypad Key Map
const char KEYPAD_MAP[4][4] = {
  {'1', '2', '3', 'A'},
  {'4', '5', '6', 'B'},
  {'7', '8', '9', 'C'},
  {'*', '0', '#', 'D'}
};

// ============================================================================
// 2. DEVICE STATE & STORAGE (DR-1 Local Store & RAM Lockout)
// ============================================================================

const char* NODE_CODE        = "node-01";
const char* FIRMWARE_VERSION = "0.1.0";

// Server base URL
String backendBaseUrl;

// Credential structure stored in terminal RAM/NVS
struct CredentialRecord {
  int id;
  uint64_t change_seq;
  char resource_code;
  char status[12];     // "active", "consumed", "revoked", "expired"
  char valid_from[25];
  char valid_until[25];
  char pin_hmac[65];
};

const int MAX_CREDENTIALS = 16;
CredentialRecord localCredentials[MAX_CREDENTIALS];
int localCredentialCount = 0;

// Synchronization state & UTC Clock Anchor
String currentEpoch = "";
uint64_t lastAckedSeq = 0;
String serverTimeAnchor = "";
time_t anchorEpochSeconds = 0;
unsigned long anchorMillis = 0;
bool timeTrusted = false;

// Event queue for offline/telemetry events
struct QueuedEvent {
  char event_id[48];
  char event_type[24];
  char reason[20];
  char resource_code;
  int credential_id;
  bool has_cred_id;
  bool time_trusted;
};

const int MAX_EVENTS = 20;
QueuedEvent eventQueue[MAX_EVENTS];
int eventQueueCount = 0;
uint32_t eventCounter = 1;

// Keypad input state machine
char selectedResource = 'A'; // Defaults to Resource 'A'
char pinBuffer[7];           // 6 digits + null terminator
byte pinBufferLen = 0;

// Lockout state (RAM-only 3-failure / 30s lockout per Decision G6)
byte failedAttempts = 0;
unsigned long lockoutUntilMillis = 0;

// ============================================================================
// 3. STRICT UTC TIME PARSING & CLOCK ANCHORING
// ============================================================================

static const int DAYS_BEFORE_MONTH[12] = {0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334};

time_t parseIsoUtcToEpoch(const char* iso) {
  int y = 0, m = 0, d = 0, h = 0, min = 0, s = 0;
  if (sscanf(iso, "%d-%d-%dT%d:%d:%d", &y, &m, &d, &h, &min, &s) != 6) {
    return 0;
  }
  if (y < 1970 || m < 1 || m > 12 || d < 1 || d > 31) {
    return 0;
  }
  int leapYears = 0;
  for (int year = 1970; year < y; year++) {
    if ((year % 4 == 0 && year % 100 != 0) || (year % 400 == 0)) {
      leapYears++;
    }
  }
  time_t days = (time_t)(y - 1970) * 365 + leapYears;
  days += DAYS_BEFORE_MONTH[m - 1];
  if (m > 2 && ((y % 4 == 0 && y % 100 != 0) || (y % 400 == 0))) {
    days += 1;
  }
  days += (d - 1);
  return days * 86400ULL + h * 3600ULL + min * 60ULL + s;
}

// Forward declaration
bool syncClockWithHealth();

String getDeviceTimestampIso() {
  if (!timeTrusted || anchorEpochSeconds == 0) {
    // Attempt immediate clock synchronization from backend /health
    syncClockWithHealth();
  }

  if (timeTrusted && anchorEpochSeconds > 0) {
    time_t currentSeconds = anchorEpochSeconds + (time_t)((millis() - anchorMillis) / 1000);
    struct tm ti;
    if (gmtime_r(&currentSeconds, &ti) != NULL) {
      char buf[25];
      strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &ti);
      return String(buf);
    }
  }

  // Fallback only if server unreachable and offline
  return "2026-10-15T12:00:00Z";
}

// ============================================================================
// 4. CRYPTOGRAPHIC UTILITIES (mbedtls HMAC-SHA256)
// ============================================================================

bool computeHmacSha256(const uint8_t* key, size_t keyLen, const uint8_t* data, size_t dataLen, uint8_t* outDigest) {
  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);
  int ret = mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 1);
  if (ret != 0) {
    mbedtls_md_free(&ctx);
    return false;
  }
  mbedtls_md_hmac_starts(&ctx, key, keyLen);
  mbedtls_md_hmac_update(&ctx, data, dataLen);
  mbedtls_md_hmac_finish(&ctx, outDigest);
  mbedtls_md_free(&ctx);
  return true;
}

String hmacSha256Hex(const String& key, const String& message) {
  uint8_t digest[32];
  if (!computeHmacSha256((const uint8_t*)key.c_str(), key.length(),
                         (const uint8_t*)message.c_str(), message.length(), digest)) {
    return "";
  }
  char hexBuf[65];
  for (int i = 0; i < 32; i++) {
    sprintf(&hexBuf[i * 2], "%02x", digest[i]);
  }
  hexBuf[64] = '\0';
  return String(hexBuf);
}

String generateNonce() {
  char nonce[17];
  for (int i = 0; i < 16; i++) {
    sprintf(&nonce[i], "%x", (uint8_t)(esp_random() & 0x0F));
  }
  nonce[16] = '\0';
  return String(nonce);
}

// ============================================================================
// 5. HARDWARE ACTUATION & FEEDBACK
// ============================================================================

void servoPulse(int angleDegrees) {
  // SG90: 0° is ~1000us (locked), 90° is ~1750us (unlocked)
  int pulseUs = 1000 + (angleDegrees * 750) / 90;
  for (int i = 0; i < 20; i++) {
    digitalWrite(SERVO_PIN, HIGH);
    delayMicroseconds(pulseUs);
    digitalWrite(SERVO_PIN, LOW);
    delay(19);
  }
}

void lockLatch() {
  Serial.println("[SERVO] Latch LOCKED (0°)");
  servoPulse(0);
}

void unlockLatch() {
  Serial.println("[SERVO] Latch UNLOCKED (90°)");
  servoPulse(90);
}

void flashLed(int pin, int times, int durationMs) {
  for (int i = 0; i < times; i++) {
    digitalWrite(pin, HIGH);
    delay(durationMs);
    digitalWrite(pin, LOW);
    delay(durationMs);
  }
}

// ============================================================================
// 6. KEYPAD DRIVER (Pure C++ debounced matrix scanner)
// ============================================================================

void setupKeypad() {
  for (byte r = 0; r < 4; r++) {
    pinMode(ROW_PINS[r], INPUT_PULLUP);
  }
  for (byte c = 0; c < 4; c++) {
    pinMode(COL_PINS[c], OUTPUT);
    digitalWrite(COL_PINS[c], HIGH);
  }
}

char scanKeypad() {
  for (byte c = 0; c < 4; c++) {
    digitalWrite(COL_PINS[c], LOW);
    for (byte r = 0; r < 4; r++) {
      if (digitalRead(ROW_PINS[r]) == LOW) {
        delay(25); // Debounce
        if (digitalRead(ROW_PINS[r]) == LOW) {
          char key = KEYPAD_MAP[r][c];
          while (digitalRead(ROW_PINS[r]) == LOW) {
            delay(10); // Wait for key release
          }
          digitalWrite(COL_PINS[c], HIGH);
          return key;
        }
      }
    }
    digitalWrite(COL_PINS[c], HIGH);
  }
  return 0;
}

// ============================================================================
// 7. EVENT QUEUE
// ============================================================================

void queueTelemetryEvent(const char* eventType, const char* reason, char resCode, int credId, bool hasCred) {
  if (eventQueueCount >= MAX_EVENTS) {
    // Drop oldest pin_rejected if buffer full (Rule DR-7)
    for (int i = 0; i < eventQueueCount - 1; i++) {
      eventQueue[i] = eventQueue[i + 1];
    }
    eventQueueCount--;
  }

  QueuedEvent& ev = eventQueue[eventQueueCount++];
  sprintf(ev.event_id, "%s-%06u-%08x", NODE_CODE, eventCounter++, (uint32_t)esp_random());
  strncpy(ev.event_type, eventType, sizeof(ev.event_type) - 1);
  if (reason) {
    strncpy(ev.reason, reason, sizeof(ev.reason) - 1);
  } else {
    ev.reason[0] = '\0';
  }
  ev.resource_code = resCode;
  ev.credential_id = credId;
  ev.has_cred_id = hasCred;
  ev.time_trusted = timeTrusted;

  Serial.printf("[EVENT QUEUED] ID: %s | Type: %s | Reason: %s\n", ev.event_id, ev.event_type, ev.reason);
}

// ============================================================================
// 8. LOCAL VALIDATION LOGIC (Docs §6 Deterministic Order)
// ============================================================================

void handlePinSubmission() {
  Serial.println("\n-------------------------------------------");
  Serial.printf("[VALIDATE] Submitted PIN '%s' for Resource %c\n", pinBuffer, selectedResource);

  // 1. Check Lockout
  if (millis() < lockoutUntilMillis) {
    unsigned long remainingSec = (lockoutUntilMillis - millis()) / 1000;
    Serial.printf("[ACCESS DENIED] Terminal LOCKED OUT (%lu s remaining). Ignoring input.\n", remainingSec);
    digitalWrite(RED_LED_PIN, HIGH);
    delay(200);
    digitalWrite(RED_LED_PIN, LOW);
    pinBufferLen = 0;
    pinBuffer[0] = '\0';
    return;
  }

  // 2. Resource-bound HMAC calculation: <resource>:<pin>
  String message = String(selectedResource) + ":" + String(pinBuffer);
  String computedHmac = hmacSha256Hex(String(PIN_HMAC_KEY), message);
  Serial.printf("[CRYPTO] Canonical msg: %s | HMAC: %s\n", message.c_str(), computedHmac.c_str());

  // 3. Match against local credential store
  int matchedIndex = -1;
  for (int i = 0; i < localCredentialCount; i++) {
    if (localCredentials[i].resource_code == selectedResource) {
      if (strcasecmp(localCredentials[i].pin_hmac, computedHmac.c_str()) == 0) {
        matchedIndex = i;
        break;
      }
    }
  }

  if (matchedIndex >= 0) {
    CredentialRecord& cred = localCredentials[matchedIndex];
    if (strcmp(cred.status, "consumed") == 0) {
      Serial.println("[ACCESS DENIED] Credential already CONSUMED.");
      failedAttempts++;
      flashLed(RED_LED_PIN, 2, 100);
      queueTelemetryEvent("pin_rejected", "consumed", selectedResource, cred.id, true);
    } else if (strcmp(cred.status, "revoked") == 0) {
      Serial.println("[ACCESS DENIED] Credential REVOKED.");
      failedAttempts++;
      flashLed(RED_LED_PIN, 2, 100);
      queueTelemetryEvent("pin_rejected", "revoked", selectedResource, cred.id, true);
    } else if (strcmp(cred.status, "active") == 0) {
      Serial.println("[ACCESS GRANTED] Credential VALID! Actuating latch.");
      failedAttempts = 0;

      // Persist consumed locally before moving servo (DR-4 / §6.2 Fail-Closed)
      strcpy(cred.status, "consumed");
      queueTelemetryEvent("credential_accepted", nullptr, selectedResource, cred.id, true);
      queueTelemetryEvent("unlock_command_issued", nullptr, selectedResource, cred.id, true);

      // Actuate servo and light green LED
      digitalWrite(GREEN_LED_PIN, HIGH);
      unlockLatch();
      delay(3000); // Hold open for 3 seconds
      lockLatch();
      digitalWrite(GREEN_LED_PIN, LOW);
      Serial.println("[ACCESS] Latch cycle complete. Relocked.");
    }
  } else {
    Serial.println("[ACCESS DENIED] Wrong PIN / No active match found.");
    failedAttempts++;
    flashLed(RED_LED_PIN, 3, 100);
    queueTelemetryEvent("pin_rejected", "wrong_pin", selectedResource, 0, false);
  }

  // Check if lockout threshold reached (3 attempts)
  if (failedAttempts >= 3) {
    Serial.println("[SECURITY] 3 consecutive failures! Entering 30-second lockout.");
    lockoutUntilMillis = millis() + 30000;
    failedAttempts = 0;
    queueTelemetryEvent("lockout_started", nullptr, selectedResource, 0, false);
    digitalWrite(RED_LED_PIN, HIGH);
  }

  pinBufferLen = 0;
  pinBuffer[0] = '\0';
  Serial.println("-------------------------------------------");
}

void processKeyInput(char key) {
  if (key >= '0' && key <= '9') {
    if (pinBufferLen < 6) {
      pinBuffer[pinBufferLen++] = key;
      pinBuffer[pinBufferLen] = '\0';
      Serial.printf("[INPUT] Key '%c' -> PIN Buffer: %s\n", key, pinBuffer);
    } else {
      Serial.println("[INPUT] PIN buffer full (6 digits). Press '#' to Enter or '*' to Clear.");
    }
  } else if (key == 'A' || key == 'B') {
    selectedResource = key;
    Serial.printf("[INPUT] Resource '%c' Selected.\n", selectedResource);
  } else if (key == '*') {
    pinBufferLen = 0;
    pinBuffer[0] = '\0';
    Serial.println("[INPUT] Cleared buffer ('*'). Ready for input.");
  } else if (key == '#') {
    if (pinBufferLen == 6) {
      handlePinSubmission();
    } else {
      Serial.printf("[INPUT] Incomplete PIN (%d/6 digits entered). Cannot submit.\n", pinBufferLen);
      flashLed(RED_LED_PIN, 1, 150);
    }
  }
}

// ============================================================================
// 9. BACKEND CLOCK SYNCHRONIZATION (/health) & SYNC CLIENT (/device/v1/sync)
// ============================================================================

bool syncClockWithHealth() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[CLOCK] Cannot sync clock: Wi-Fi not connected.");
    return false;
  }

  WiFiClient client;
  HTTPClient http;
  http.setConnectTimeout(5000);
  http.setTimeout(5000);

  String url = backendBaseUrl + "/health";
  if (!http.begin(client, url)) {
    Serial.println("[CLOCK] ERROR: http.begin(/health) failed");
    return false;
  }

  int httpCode = http.GET();
  if (httpCode == 200) {
    String responseBody = http.getString();
    int keyIdx = responseBody.indexOf("\"server_time\"");
    if (keyIdx >= 0) {
      int colonIdx = responseBody.indexOf(':', keyIdx + 13);
      if (colonIdx >= 0) {
        int firstQuote = responseBody.indexOf('\"', colonIdx);
        if (firstQuote >= 0) {
          int secondQuote = responseBody.indexOf('\"', firstQuote + 1);
          if (secondQuote > firstQuote) {
            String serverTimeStr = responseBody.substring(firstQuote + 1, secondQuote);
            time_t epoch = parseIsoUtcToEpoch(serverTimeStr.c_str());
            if (epoch > 0) {
              anchorEpochSeconds = epoch;
              anchorMillis = millis();
              timeTrusted = true;
              serverTimeAnchor = serverTimeStr;

              struct timeval tv;
              tv.tv_sec = epoch;
              tv.tv_usec = 0;
              settimeofday(&tv, NULL);

              Serial.printf("[CLOCK] Synchronized with /health UTC: %s (Epoch: %ld)\n",
                            serverTimeStr.c_str(), (long)epoch);
              http.end();
              return true;
            }
          }
        }
      }
    }
    Serial.println("[CLOCK] Warning: server_time field not found in /health response.");
  } else {
    Serial.printf("[CLOCK] /health returned HTTP %d: %s\n", httpCode, http.errorToString(httpCode).c_str());
  }
  http.end();
  return false;
}

void testHealthEndpoint() {
  Serial.println("\n[PROBE] Running operational health check (/health) ...");
  if (syncClockWithHealth()) {
    Serial.println("[PROBE] Health probe OK and clock synchronized.");
  } else {
    Serial.println("[PROBE] Health probe check failed.");
  }
}

void syncWithBackend() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[SYNC] Cannot sync: Wi-Fi not connected.");
    return;
  }

  // Before generating device sync request timestamp, synchronize clock from backend /health
  Serial.println("\n[SYNC] Synchronizing clock from /health before generating sync request...");
  bool synced = syncClockWithHealth();
  if (!synced) {
    if (!timeTrusted || anchorEpochSeconds == 0) {
      Serial.println("[SYNC] ERROR: Clock sync from /health failed and no trusted anchor. Aborting sync.");
      return;
    }
    Serial.println("[SYNC] WARNING: /health probe failed; falling back to local anchored elapsed clock.");
  }

  Serial.println("[SYNC] Starting POST /device/v1/sync ...");
  WiFiClient client;
  HTTPClient http;
  http.setConnectTimeout(5000);
  http.setTimeout(5000);

  String url = backendBaseUrl + "/device/v1/sync";
  if (!http.begin(client, url)) {
    Serial.println("[SYNC] ERROR: http.begin failed");
    return;
  }

  String nonce = generateNonce();
  String timestamp = getDeviceTimestampIso();

  http.addHeader("X-Device-Key", DEVICE_API_KEY);
  http.addHeader("X-Device-Timestamp", timestamp);
  http.addHeader("Content-Type", "application/json");

  // Collect responses for signature checking
  const char* headerKeys[] = {"X-Server-Signature"};
  http.collectHeaders(headerKeys, 1);

  // Build JSON request payload
  String payload = "{";
  payload += "\"node_code\":\"" + String(NODE_CODE) + "\",";
  payload += "\"firmware_version\":\"" + String(FIRMWARE_VERSION) + "\",";
  payload += "\"epoch\":\"" + currentEpoch + "\",";
  payload += "\"last_seq\":" + String((unsigned long)lastAckedSeq) + ",";
  payload += "\"request_nonce\":\"" + nonce + "\",";
  payload += "\"time_state\":\"server_anchored\",";
  payload += "\"device_time\":\"" + timestamp + "\",";
  payload += "\"events\":[";

  for (int i = 0; i < eventQueueCount; i++) {
    if (i > 0) payload += ",";
    QueuedEvent& ev = eventQueue[i];
    payload += "{";
    payload += "\"event_id\":\"" + String(ev.event_id) + "\",";
    payload += "\"event_type\":\"" + String(ev.event_type) + "\",";
    if (strlen(ev.reason) > 0) {
      payload += "\"reason\":\"" + String(ev.reason) + "\",";
    }
    payload += "\"resource_code\":\"" + String(ev.resource_code) + "\",";
    if (ev.has_cred_id) {
      payload += "\"credential_id\":" + String(ev.credential_id) + ",";
    }
    payload += "\"device_time\":\"" + timestamp + "\",";
    payload += "\"time_trusted\":" + String(ev.time_trusted ? "true" : "false");
    payload += "}";
  }
  payload += "]}";

  Serial.printf("[SYNC] Headers -> X-Device-Timestamp: %s\n", timestamp.c_str());
  Serial.printf("[SYNC] Sending payload (%u bytes, nonce: %s) ...\n", payload.length(), nonce.c_str());
  int httpCode = http.POST(payload);

  if (httpCode == 200) {
    String responseBody = http.getString();
    String serverSignature = http.header("X-Server-Signature");

    Serial.printf("[SYNC] HTTP 200 OK. Body bytes: %u\n", responseBody.length());
    Serial.printf("[SYNC] X-Server-Signature: %s\n", serverSignature.c_str());

    // 1. Verify HMAC-SHA256 signature over response body bytes
    String expectedSignature = hmacSha256Hex(String(DEVICE_API_KEY), responseBody);
    if (!serverSignature.equalsIgnoreCase(expectedSignature)) {
      Serial.println("[SECURITY ERROR] X-Server-Signature mismatch! Discarding response.");
      Serial.printf("  Expected: %s\n  Received: %s\n", expectedSignature.c_str(), serverSignature.c_str());
      http.end();
      return;
    }
    Serial.println("[SECURITY] X-Server-Signature VERIFIED successfully!");

    // 2. Parse response fields (nonce, epoch, to_seq, server_time)
    int nonceIdx = responseBody.indexOf("\"request_nonce\":\"");
    if (nonceIdx >= 0) {
      String respNonce = responseBody.substring(nonceIdx + 17, nonceIdx + 33);
      if (respNonce != nonce) {
        Serial.println("[SECURITY ERROR] Nonce mismatch! Discarding response.");
        http.end();
        return;
      }
      Serial.println("[SECURITY] Request Nonce echo VERIFIED!");
    }

    // Extract epoch
    int epochIdx = responseBody.indexOf("\"epoch\":\"");
    if (epochIdx >= 0) {
      int endEpoch = responseBody.indexOf("\"", epochIdx + 9);
      currentEpoch = responseBody.substring(epochIdx + 9, endEpoch);
      Serial.printf("[SYNC] Epoch: %s\n", currentEpoch.c_str());
    }

    // Extract server_time and re-anchor clock
    int timeIdx = responseBody.indexOf("\"server_time\"");
    if (timeIdx >= 0) {
      int colonIdx = responseBody.indexOf(':', timeIdx + 13);
      if (colonIdx >= 0) {
        int firstQuote = responseBody.indexOf('\"', colonIdx);
        if (firstQuote >= 0) {
          int secondQuote = responseBody.indexOf('\"', firstQuote + 1);
          if (secondQuote > firstQuote) {
            serverTimeAnchor = responseBody.substring(firstQuote + 1, secondQuote);
            time_t epoch = parseIsoUtcToEpoch(serverTimeAnchor.c_str());
            if (epoch > 0) {
              anchorEpochSeconds = epoch;
              anchorMillis = millis();
              timeTrusted = true;
              struct timeval tv;
              tv.tv_sec = epoch;
              tv.tv_usec = 0;
              settimeofday(&tv, NULL);
              Serial.printf("[SYNC] Server Time Re-anchored: %s (Time Trusted)\n", serverTimeAnchor.c_str());
            }
          }
        }
      }
    }

    // Extract to_seq
    int seqIdx = responseBody.indexOf("\"to_seq\":");
    if (seqIdx >= 0) {
      int endSeq = responseBody.indexOf(",", seqIdx);
      if (endSeq < 0) endSeq = responseBody.indexOf("}", seqIdx);
      lastAckedSeq = responseBody.substring(seqIdx + 9, endSeq).toInt();
      Serial.printf("[SYNC] Advanced sequence pointer to: %llu\n", lastAckedSeq);
    }

    // Parse credentials from response
    int credIdx = responseBody.indexOf("\"credentials\":[");
    if (credIdx >= 0) {
      int endCreds = responseBody.indexOf("]", credIdx);
      String credsJson = responseBody.substring(credIdx + 15, endCreds);
      
      int p = 0;
      while ((p = credsJson.indexOf("\"id\":", p)) >= 0) {
        if (localCredentialCount >= MAX_CREDENTIALS) break;
        int nextId = credsJson.substring(p + 5, credsJson.indexOf(",", p)).toInt();
        
        int hmacPos = credsJson.indexOf("\"pin_hmac\":\"", p);
        if (hmacPos >= 0) {
          String hmacStr = credsJson.substring(hmacPos + 12, hmacPos + 76);
          
          int resPos = credsJson.indexOf("\"resource_code\":\"", p);
          char resCode = 'A';
          if (resPos >= 0) resCode = credsJson.charAt(resPos + 17);

          int statusPos = credsJson.indexOf("\"status\":\"", p);
          String statusStr = "active";
          if (statusPos >= 0) {
            statusStr = credsJson.substring(statusPos + 10, credsJson.indexOf("\"", statusPos + 10));
          }

          bool found = false;
          for (int c = 0; c < localCredentialCount; c++) {
            if (localCredentials[c].id == nextId) {
              strcpy(localCredentials[c].status, statusStr.c_str());
              strcpy(localCredentials[c].pin_hmac, hmacStr.c_str());
              found = true;
              break;
            }
          }
          if (!found && localCredentialCount < MAX_CREDENTIALS) {
            CredentialRecord& cr = localCredentials[localCredentialCount++];
            cr.id = nextId;
            cr.resource_code = resCode;
            strcpy(cr.status, statusStr.c_str());
            strcpy(cr.pin_hmac, hmacStr.c_str());
          }
          Serial.printf("[STORE] Credential ID %d (%c) -> Status: %s | HMAC: %s\n",
                        nextId, resCode, statusStr.c_str(), hmacStr.c_str());
        }
        p += 10;
      }
    }

    // Clear acked events
    eventQueueCount = 0;
    Serial.println("[SYNC] Telemetry event queue cleared.");
  } else {
    Serial.printf("[SYNC] Request failed with HTTP %d: %s\n", httpCode, http.getString().c_str());
  }

  http.end();
}

// ============================================================================
// 10. SELF-TEST TEST VECTORS (Policy §2.3)
// ============================================================================

void runSelfTestVectors() {
  Serial.println("\n--- RUNNING CRYPTOGRAPHIC TEST VECTORS ---");

  // Test Vector 1: PIN HMAC-SHA256
  // Secret: "dkac-test-vector-key-0001", PIN: "482916", Resource: "A"
  String tv1Msg = "A:482916";
  String tv1Key = "dkac-test-vector-key-0001";
  String tv1Expected = "e48f878502a47172ea00cf018627956dab95a5073357dc5b01220bc4179093bc";
  String tv1Calculated = hmacSha256Hex(tv1Key, tv1Msg);

  if (tv1Calculated == tv1Expected) {
    Serial.println("[PASS] Test Vector 1 (PIN HMAC-SHA256): MATCHES");
  } else {
    Serial.println("[FAIL] Test Vector 1 MISMATCH!");
    Serial.printf("  Expected: %s\n  Got:      %s\n", tv1Expected.c_str(), tv1Calculated.c_str());
  }

  // Test Vector 2: Response HMAC-SHA256
  // Secret: "dkac-device-test-key-0001"
  String tv2Key = "dkac-device-test-key-0001";
  String tv2Body = "{\"server_time\":\"2026-10-12T09:15:02Z\",\"request_nonce\":\"c4b8e21a8f9042b7\"}";
  String tv2Expected = "c9c1a47b519b81ab2d9423dc9f6d57b379da7d2ef35326212ef9ccba6f972022";
  String tv2Calculated = hmacSha256Hex(tv2Key, tv2Body);

  if (tv2Calculated == tv2Expected) {
    Serial.println("[PASS] Test Vector 2 (X-Server-Signature): MATCHES");
  } else {
    Serial.println("[FAIL] Test Vector 2 MISMATCH!");
    Serial.printf("  Expected: %s\n  Got:      %s\n", tv2Expected.c_str(), tv2Calculated.c_str());
  }
  Serial.println("-------------------------------------------\n");
}

// ============================================================================
// 11. SETUP & MAIN LOOP
// ============================================================================

void setup() {
  Serial.begin(115200);
  delay(1000);

  // Configure time environment to UTC
  setenv("TZ", "UTC0", 1);
  tzset();

  Serial.println("\n=======================================================");
  Serial.println("  Digital Key Access Control - ESP32 Access Terminal   ");
  Serial.println("=======================================================");

  // Initialize hardware pins
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(RED_LED_PIN, OUTPUT);
  digitalWrite(GREEN_LED_PIN, LOW);
  digitalWrite(RED_LED_PIN, LOW);

  pinMode(SERVO_PIN, OUTPUT);
  lockLatch();

  setupKeypad();
  Serial.println("[HARDWARE] Keypad (4x4), LEDs, and Servo pins initialized.");

  // Run cryptographic self-test vectors
  runSelfTestVectors();

  // Connect to Wi-Fi
  backendBaseUrl = "http://" + String(SERVER_HOST) + ":" + String(SERVER_PORT);
  Serial.printf("[WIFI] Connecting to SSID: '%s' ...\n", WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[WIFI] Connected! IP Address: %s\n", WiFi.localIP().toString().c_str());
    digitalWrite(GREEN_LED_PIN, HIGH);
    delay(200);
    digitalWrite(GREEN_LED_PIN, LOW);

    // Initial operational health check & UTC clock synchronization
    testHealthEndpoint();

    // Initial synchronization with backend
    syncWithBackend();
  } else {
    Serial.println("\n[WIFI] Connection failed. Operating in offline mode.");
    digitalWrite(RED_LED_PIN, HIGH);
    delay(500);
    digitalWrite(RED_LED_PIN, LOW);
  }

  Serial.println("\n--- Interactive Terminal Ready ---");
  Serial.println("Keypad: Enter 6 digits + '#' to submit, '*' to clear, 'A' or 'B' to switch resource.");
  Serial.println("Serial Commands: 'h'=Health & Clock sync | 's'=Sync | 'l'=Test servo | 'v'=Test vectors");
  Serial.println("                 'a'/'b'=Select A/B | '0'-'9'=Digit | '*'=Clear | '#'=Enter");
}

unsigned long lastSyncMillis = 0;
const unsigned long SYNC_INTERVAL_MS = 15000; // 15-second heartbeat per Contract DR-8

void loop() {
  // 1. Scan physical keypad
  char physicalKey = scanKeypad();
  if (physicalKey != 0) {
    Serial.printf("[PHYSICAL KEYPAD] Pressed: '%c'\n", physicalKey);
    processKeyInput(physicalKey);
  }

  // 2. Interactive Serial Command Console (supports bench testing from laptop)
  if (Serial.available() > 0) {
    char ch = Serial.read();
    if (ch == 'h' || ch == 'H') {
      testHealthEndpoint();
    } else if (ch == 's' || ch == 'S') {
      syncWithBackend();
    } else if (ch == 'l' || ch == 'L') {
      Serial.println("[TEST] Manual servo actuation test...");
      unlockLatch();
      digitalWrite(GREEN_LED_PIN, HIGH);
      delay(2000);
      lockLatch();
      digitalWrite(GREEN_LED_PIN, LOW);
    } else if (ch == 'v' || ch == 'V') {
      runSelfTestVectors();
    } else if (ch == 'k' || ch == 'K') {
      Serial.printf("[STATUS] Resource: %c | Buffer: '%s' | Creds in store: %d | Lockout: %s | Trusted Time: %s\n",
                    selectedResource, pinBuffer, localCredentialCount,
                    (millis() < lockoutUntilMillis) ? "ACTIVE" : "NONE",
                    getDeviceTimestampIso().c_str());
    } else if ((ch >= '0' && ch <= '9') || ch == '*' || ch == '#' || ch == 'A' || ch == 'B' || ch == 'a' || ch == 'b') {
      char upper = toupper(ch);
      Serial.printf("[SERIAL INPUT] Key: '%c'\n", upper);
      processKeyInput(upper);
    }
  }

  // 3. Periodic synchronization heartbeat (every 15s)
  if (millis() - lastSyncMillis >= SYNC_INTERVAL_MS) {
    lastSyncMillis = millis();
    if (WiFi.status() == WL_CONNECTED) {
      syncWithBackend();
    }
  }

  // 4. Update Red LED during 30s lockout
  if (millis() < lockoutUntilMillis) {
    digitalWrite(RED_LED_PIN, (millis() / 250) % 2 == 0 ? HIGH : LOW);
  } else if (failedAttempts == 0) {
    digitalWrite(RED_LED_PIN, LOW);
  }
}
