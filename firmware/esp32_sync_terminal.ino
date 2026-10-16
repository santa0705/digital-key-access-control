#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <time.h>
#include <Wire.h>
#include <DIYables_LCD_I2C.h>
#include <sys/time.h>
#include "mbedtls/md.h"
#include "secrets.h"

// Hardware pins — keep unchanged
const byte ROW_PINS[4] = {19, 18, 5, 17};
const byte COL_PINS[4] = {23, 22, 21, 16};

const int SERVO_PIN = 13;
const int LCD_SDA_PIN = 26;
const int LCD_SCL_PIN = 27;
DIYables_LCD_I2C lcd(0x27, 16, 2);

const char KEYPAD_MAP[4][4] = {
  {'1', '2', '3', 'A'},
  {'4', '5', '6', 'B'},
  {'7', '8', '9', 'C'},
  {'*', '0', '#', 'D'}
};

const char* NODE_CODE = "node-01";
const char* FIRMWARE_VERSION = "0.1.0";

String backendBaseUrl;

// Trusted GTS Root R4 certificate
static const char ROOT_CA[] PROGMEM = R"CERT(
-----BEGIN CERTIFICATE-----
MIICCTCCAY6gAwIBAgINAgPlwGjvYxqccpBQUjAKBggqhkjOPQQDAzBHMQswCQYD
VQQGEwJVUzEiMCAGA1UEChMZR29vZ2xlIFRydXN0IFNlcnZpY2VzIExMQzEUMBIG
A1UEAxMLR1RTIFJvb3QgUjQwHhcNMTYwNjIyMDAwMDAwWhcNMzYwNjIyMDAwMDAw
WjBHMQswCQYDVQQGEwJVUzEiMCAGA1UEChMZR29vZ2xlIFRydXN0IFNlcnZpY2Vz
IExMQzEUMBIGA1UEAxMLR1RTIFJvb3QgUjQwdjAQBgcqhkjOPQIBBgUrgQQAIgNi
AATzdHOnaItgrkO4NcWBMHtLSZ37wWHO5t5GvWvVYRg1rkDdc/eJkTBa6zzuhXyi
QHY7qca4R9gq55KRanPpsXI5nymfopjTX15YhmUPoYRlBtHci8nHc8iMai/lxKvR
HYqjQjBAMA4GA1UdDwEB/wQEAwIBhjAPBgNVHRMBAf8EBTADAQH/MB0GA1UdDgQW
BBSATNbrdP9JNqPV2Py1PsVq8JQdjDAKBggqhkjOPQQDAwNpADBmAjEA6ED/g94D
9J+uHXqnLrmvT/aDHQ4thQEd0dlq7A/Cr8deVl5c1RxYIigL9zC2L7F8AjEA8GE8
p/SgguMh1YQdc4acLa/KNJvxn7kjNuK8YAOdgLOaVsjh4rsUecrNIdSUtUlD
-----END CERTIFICATE-----
)CERT";

struct CredentialRecord {
  int id;
  uint64_t change_seq;
  char resource_code;
  char status[12];
  char valid_from[25];
  char valid_until[25];
  char pin_hmac[65];
};

const int MAX_CREDENTIALS = 16;
CredentialRecord localCredentials[MAX_CREDENTIALS];
int localCredentialCount = 0;

String currentEpoch = "";
uint64_t lastAckedSeq = 0;
String serverTimeAnchor = "";

time_t anchorEpochSeconds = 0;
unsigned long anchorMillis = 0;
bool timeTrusted = false;

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

char selectedResource = 'A';
char pinBuffer[7];
byte pinBufferLen = 0;

byte failedAttempts = 0;
unsigned long lockoutUntilMillis = 0;

static const int DAYS_BEFORE_MONTH[12] = {
  0, 31, 59, 90, 120, 151,
  181, 212, 243, 273, 304, 334
};

time_t parseIsoUtcToEpoch(const char* iso) {
  int y = 0, m = 0, d = 0;
  int h = 0, min = 0, s = 0;

  if (sscanf(iso, "%d-%d-%dT%d:%d:%d",
             &y, &m, &d, &h, &min, &s) != 6) {
    return 0;
  }

  if (y < 1970 || m < 1 || m > 12 || d < 1 || d > 31) {
    return 0;
  }

  int leapYears = 0;
  for (int year = 1970; year < y; year++) {
    if ((year % 4 == 0 && year % 100 != 0) ||
        (year % 400 == 0)) {
      leapYears++;
    }
  }

  time_t days = (time_t)(y - 1970) * 365 + leapYears;
  days += DAYS_BEFORE_MONTH[m - 1];

  if (m > 2 &&
      ((y % 4 == 0 && y % 100 != 0) || (y % 400 == 0))) {
    days++;
  }

  days += d - 1;
  return days * 86400ULL + h * 3600ULL + min * 60ULL + s;
}

bool syncClockWithHealth();

String getDeviceTimestampIso() {
  if (!timeTrusted || anchorEpochSeconds == 0) {
    syncClockWithHealth();
  }

  if (timeTrusted && anchorEpochSeconds > 0) {
    time_t currentSeconds =
      anchorEpochSeconds + (time_t)((millis() - anchorMillis) / 1000);

    struct tm ti;
    if (gmtime_r(&currentSeconds, &ti) != NULL) {
      char buf[25];
      strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &ti);
      return String(buf);
    }
  }

  return "";
}

bool computeHmacSha256(
  const uint8_t* key,
  size_t keyLen,
  const uint8_t* data,
  size_t dataLen,
  uint8_t* outDigest
) {
  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);

  int ret = mbedtls_md_setup(
    &ctx,
    mbedtls_md_info_from_type(MBEDTLS_MD_SHA256),
    1
  );

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

  if (!computeHmacSha256(
        (const uint8_t*)key.c_str(), key.length(),
        (const uint8_t*)message.c_str(), message.length(),
        digest)) {
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
// 7. EVENT QUEUE
// ============================================================================

void queueTelemetryEvent(const char* eventType, const char* reason,
                         char resCode, int credId, bool hasCred) {
  if (eventQueueCount >= MAX_EVENTS) {
    for (int i = 0; i < eventQueueCount - 1; i++) {
      eventQueue[i] = eventQueue[i + 1];
    }
    eventQueueCount--;
  }

  QueuedEvent& ev = eventQueue[eventQueueCount++];

  sprintf(ev.event_id, "%s-%06u-%08x",
          NODE_CODE, eventCounter++, (uint32_t)esp_random());

  strncpy(ev.event_type, eventType, sizeof(ev.event_type) - 1);
  ev.event_type[sizeof(ev.event_type) - 1] = '\0';

  if (reason) {
    strncpy(ev.reason, reason, sizeof(ev.reason) - 1);
    ev.reason[sizeof(ev.reason) - 1] = '\0';
  } else {
    ev.reason[0] = '\0';
  }

  ev.resource_code = resCode;
  ev.credential_id = credId;
  ev.has_cred_id = hasCred;
  ev.time_trusted = timeTrusted;

  Serial.printf("[EVENT QUEUED] ID: %s | Type: %s | Reason: %s\n",
                ev.event_id, ev.event_type, ev.reason);
}


/* ============================================================
   HARDWARE HELPERS — RESTORE MISSING FUNCTIONS
   Uses existing SERVO_PIN, ROW_PINS, COL_PINS and KEYPAD_MAP
   ============================================================ */

// Typical SG90 pulse range. If the linkage hits a hard stop, reduce these
// limits slightly to avoid straining the servo or its power supply.
const int SERVO_MIN_US = 500;   // approximately 0 degrees
const int SERVO_MAX_US = 2500;  // approximately 180 degrees

void servoPulse(int angleDegrees) {
  angleDegrees = constrain(angleDegrees, 0, 180);
  int pulseUs = SERVO_MIN_US +
                ((long)angleDegrees * (SERVO_MAX_US - SERVO_MIN_US)) / 180;

  // Repeat pulses long enough for the servo to reach the requested position.
  for (int i = 0; i < 30; i++) {
    digitalWrite(SERVO_PIN, HIGH);
    delayMicroseconds(pulseUs);
    digitalWrite(SERVO_PIN, LOW);
    delay(20);
  }
}

void lockLatch() {
  Serial.println("[SERVO] Latch returned to 0 degrees");
  servoPulse(0);
}

void unlockLatch() {
  Serial.println("[SERVO] Latch moved to 180 degrees");
  servoPulse(180);
}

void showLCD(const String& line1, const String& line2 = "") {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(line1.substring(0, 16));
  lcd.setCursor(0, 1);
  lcd.print(line2.substring(0, 16));
}

void setupLCD() {
  Wire.begin(LCD_SDA_PIN, LCD_SCL_PIN);
  lcd.init();
  lcd.backlight();
  showLCD("Digital Locker", "Starting...");
}

void showPinPrompt() {
  String masked = "PIN: ";
  for (byte i = 0; i < pinBufferLen; i++) masked += '*';
  showLCD(String("Resource ") + selectedResource, masked);
}

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
        delay(25);

        if (digitalRead(ROW_PINS[r]) == LOW) {
          char key = KEYPAD_MAP[r][c];

          // Wait until the key is released.
          while (digitalRead(ROW_PINS[r]) == LOW) {
            delay(10);
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
// 8. LOCAL VALIDATION LOGIC
// ============================================================================

void handlePinSubmission() {
  Serial.println("\n-------------------------------------------");
  Serial.printf("[VALIDATE] Submitted PIN '%s' for Resource %c\n",
                pinBuffer, selectedResource);

  if (millis() < lockoutUntilMillis) {
    unsigned long remainingSec =
      (lockoutUntilMillis - millis()) / 1000;

    Serial.printf("[ACCESS DENIED] Terminal LOCKED OUT (%lu s remaining).\n",
                  remainingSec);
    showLCD("ACCESS LOCKED", String(remainingSec) + " sec remaining");


    pinBufferLen = 0;
    pinBuffer[0] = '\0';
    return;
  }

  String message = String(selectedResource) + ":" + String(pinBuffer);
  String computedHmac = hmacSha256Hex(String(PIN_HMAC_KEY), message);

  Serial.printf("[CRYPTO] Canonical msg: %s | HMAC: %s\n",
                message.c_str(), computedHmac.c_str());

  int matchedIndex = -1;

  for (int i = 0; i < localCredentialCount; i++) {
    if (localCredentials[i].resource_code == selectedResource &&
        strcasecmp(localCredentials[i].pin_hmac,
                   computedHmac.c_str()) == 0) {
      matchedIndex = i;
      break;
    }
  }

  if (matchedIndex >= 0) {
    CredentialRecord& cred = localCredentials[matchedIndex];

    if (strcmp(cred.status, "consumed") == 0) {
      Serial.println("[ACCESS DENIED] Credential already CONSUMED.");
      showLCD("PIN REJECTED", "Already used");
      failedAttempts++;
      queueTelemetryEvent("pin_rejected", "consumed",
                          selectedResource, cred.id, true);

    } else if (strcmp(cred.status, "revoked") == 0) {
      Serial.println("[ACCESS DENIED] Credential REVOKED.");
      showLCD("PIN REJECTED", "Revoked PIN");
      failedAttempts++;
      queueTelemetryEvent("pin_rejected", "revoked",
                          selectedResource, cred.id, true);

    } else if (strcmp(cred.status, "active") == 0) {
      Serial.println("[ACCESS GRANTED] Credential VALID! Actuating latch.");
      showLCD("ACCESS GRANTED", "Unlocking...");
      failedAttempts = 0;

      strcpy(cred.status, "consumed");

      queueTelemetryEvent("credential_accepted", nullptr,
                          selectedResource, cred.id, true);
      queueTelemetryEvent("unlock_command_issued", nullptr,
                          selectedResource, cred.id, true);

      unlockLatch();
      delay(3000);
      lockLatch();

      Serial.println("[ACCESS] Latch cycle complete. Relocked.");
      showLCD("Door locked", "Enter PIN:");
    }

  } else {
    Serial.println("[ACCESS DENIED] Wrong PIN / No active match found.");
    showLCD("ACCESS DENIED", "Invalid PIN");
    failedAttempts++;
    queueTelemetryEvent("pin_rejected", "wrong_pin",
                        selectedResource, 0, false);
  }

  if (failedAttempts >= 3) {
    Serial.println("[SECURITY] 3 consecutive failures! 30-second lockout.");
    showLCD("Too many tries", "Wait 30 seconds");
    lockoutUntilMillis = millis() + 30000;
    failedAttempts = 0;

    queueTelemetryEvent("lockout_started", nullptr,
                        selectedResource, 0, false);
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

      Serial.printf("[INPUT] Key '%c' -> PIN Buffer: %s\n",
                    key, pinBuffer);
      showPinPrompt();
    } else {
      Serial.println("[INPUT] PIN buffer full. Press '#' to submit or '*' to clear.");
    }

  } else if (key == 'A' || key == 'B') {
    selectedResource = key;
    Serial.printf("[INPUT] Resource '%c' Selected.\n", selectedResource);
    showPinPrompt();

  } else if (key == '*') {
    pinBufferLen = 0;
    pinBuffer[0] = '\0';
    Serial.println("[INPUT] Cleared buffer ('*'). Ready for input.");
    showPinPrompt();

  } else if (key == '#') {
    if (pinBufferLen == 6) {
      handlePinSubmission();
    } else {
      Serial.printf("[INPUT] Incomplete PIN (%d/6 digits entered).\n",
                    pinBufferLen);
      showLCD("PIN incomplete", String(pinBufferLen) + "/6 digits");
    }
  }
}

// ============================================================================
// 9. BACKEND CLOCK SYNCHRONIZATION
// ============================================================================

bool syncClockWithHealth() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[CLOCK] Cannot sync clock: Wi-Fi not connected.");
    return false;
  }

  WiFiClientSecure client;
  client.setCACert(ROOT_CA);

  HTTPClient http;
  http.setConnectTimeout(5000);
  http.setTimeout(5000);

  String url = backendBaseUrl + "/health";

  if (!http.begin(client, url)) {
    Serial.println("[CLOCK] ERROR: http.begin(/health) failed");
    return false;
  }

  Serial.printf("[DEBUG] URL: %s\n", url.c_str());
  Serial.printf("[DEBUG] WiFi status before request: %d\n", WiFi.status());
  Serial.printf("[DEBUG] Free heap before request: %u\n", ESP.getFreeHeap());

  char tlsError[200] = {0};
  int httpCode = http.GET();
  client.lastError(tlsError, sizeof(tlsError));
  Serial.printf("[TLS DEBUG] %s\n", tlsError);

  if (httpCode == 200) {
    String responseBody = http.getString();

    int keyIdx = responseBody.indexOf("\"server_time\"");
    if (keyIdx >= 0) {
      int colonIdx = responseBody.indexOf(':', keyIdx + 13);

      if (colonIdx >= 0) {
        int firstQuote = responseBody.indexOf('"', colonIdx);

        if (firstQuote >= 0) {
          int secondQuote =
            responseBody.indexOf('"', firstQuote + 1);

          if (secondQuote > firstQuote) {
            String serverTimeStr =
              responseBody.substring(firstQuote + 1, secondQuote);

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

              Serial.printf(
                "[CLOCK] Synchronized with /health UTC: %s (Epoch: %ld)\n",
                serverTimeStr.c_str(), (long)epoch
              );

              http.end();
              return true;
            }
          }
        }
      }
    }

    Serial.println("[CLOCK] Warning: server_time field not found in /health response.");

  } else {
    Serial.printf("[CLOCK] /health returned HTTP %d: %s\n",
                  httpCode, http.errorToString(httpCode).c_str());
    Serial.printf("[DEBUG] WiFi status after request: %d\n", WiFi.status());
    Serial.printf("[DEBUG] Free heap after request: %u\n", ESP.getFreeHeap());
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
// ============================================================================
// 10. BACKEND SYNC CLIENT
// ============================================================================

void syncWithBackend() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[SYNC] Cannot sync: Wi-Fi not connected.");
    return;
  }

  Serial.println(
    "\n[SYNC] Synchronizing clock from /health before generating sync request..."
  );

  bool synced = syncClockWithHealth();

  if (!synced) {
    if (!timeTrusted || anchorEpochSeconds == 0) {
      Serial.println(
        "[SYNC] ERROR: Clock sync failed and no trusted anchor. Aborting sync."
      );
      return;
    }

    Serial.println(
      "[SYNC] WARNING: /health failed; using local anchored elapsed clock."
    );
  }

  Serial.println("[SYNC] Starting POST /device/v1/sync ...");

  WiFiClientSecure client;
  client.setCACert(ROOT_CA);

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

  const char* headerKeys[] = {"X-Server-Signature"};
  http.collectHeaders(headerKeys, 1);

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
    payload += "\"time_trusted\":";
    payload += ev.time_trusted ? "true" : "false";
    payload += "}";
  }

  payload += "]}";

  Serial.printf("[SYNC] Timestamp: %s\n", timestamp.c_str());
  Serial.printf("[SYNC] Payload bytes: %u\n", payload.length());

  int httpCode = http.POST(payload);

  if (httpCode == 200) {
    String responseBody = http.getString();
    String serverSignature = http.header("X-Server-Signature");

    Serial.printf("[SYNC] HTTP 200 OK. Body bytes: %u\n",
                  responseBody.length());

    // Verify response HMAC.
    String expectedSignature =
      hmacSha256Hex(String(DEVICE_API_KEY), responseBody);

    if (!serverSignature.equalsIgnoreCase(expectedSignature)) {
      Serial.println(
        "[SECURITY ERROR] Signature mismatch. Discarding response."
      );
      http.end();
      return;
    }

    Serial.println("[SECURITY] X-Server-Signature VERIFIED.");

    // Verify echoed request nonce.
    int nonceIdx = responseBody.indexOf("\"request_nonce\":\"");

    if (nonceIdx < 0) {
      Serial.println("[SECURITY ERROR] Response nonce missing.");
      http.end();
      return;
    }

    String respNonce =
      responseBody.substring(nonceIdx + 17, nonceIdx + 33);

    if (respNonce != nonce) {
      Serial.println("[SECURITY ERROR] Nonce mismatch.");
      http.end();
      return;
    }

    Serial.println("[SECURITY] Request nonce VERIFIED.");

    // Extract epoch.
    int epochIdx = responseBody.indexOf("\"epoch\":\"");

    if (epochIdx >= 0) {
      int start = epochIdx + 9;
      int end = responseBody.indexOf('"', start);

      if (end > start) {
        currentEpoch = responseBody.substring(start, end);
        Serial.printf("[SYNC] Epoch: %s\n", currentEpoch.c_str());
      }
    }

    // Re-anchor trusted time from the signed response.
    int timeIdx = responseBody.indexOf("\"server_time\"");

    if (timeIdx >= 0) {
      int colonIdx = responseBody.indexOf(':', timeIdx + 13);
      int firstQuote = responseBody.indexOf('"', colonIdx);
      int secondQuote = responseBody.indexOf('"', firstQuote + 1);

      if (colonIdx >= 0 && firstQuote >= 0 &&
          secondQuote > firstQuote) {
        serverTimeAnchor =
          responseBody.substring(firstQuote + 1, secondQuote);

        time_t epoch =
          parseIsoUtcToEpoch(serverTimeAnchor.c_str());

        if (epoch > 0) {
          anchorEpochSeconds = epoch;
          anchorMillis = millis();
          timeTrusted = true;

          struct timeval tv;
          tv.tv_sec = epoch;
          tv.tv_usec = 0;
          settimeofday(&tv, NULL);

          Serial.printf(
            "[SYNC] Server time re-anchored: %s\n",
            serverTimeAnchor.c_str()
          );
        }
      }
    }

    // Extract sequence pointer.
    int seqIdx = responseBody.indexOf("\"to_seq\":");

    if (seqIdx >= 0) {
      int start = seqIdx + 9;
      int end = responseBody.indexOf(',', start);

      if (end < 0) {
        end = responseBody.indexOf('}', start);
      }

      if (end > start) {
        lastAckedSeq =
          responseBody.substring(start, end).toInt();

        Serial.printf(
          "[SYNC] Sequence pointer: %llu\n",
          lastAckedSeq
        );
      }
    }

    // Parse credentials from the response.
    int credIdx = responseBody.indexOf("\"credentials\":[");

    if (credIdx >= 0) {
      int endCreds = responseBody.indexOf(']', credIdx);

      if (endCreds > credIdx) {
        String credsJson =
          responseBody.substring(credIdx + 15, endCreds);

        int p = 0;

        while ((p = credsJson.indexOf("\"id\":", p)) >= 0) {
          if (localCredentialCount >= MAX_CREDENTIALS) break;

          int idStart = p + 5;
          int idEnd = credsJson.indexOf(',', idStart);

          if (idEnd < 0) break;

          int nextId =
            credsJson.substring(idStart, idEnd).toInt();

          int hmacPos = credsJson.indexOf("\"pin_hmac\":\"", p);
          if (hmacPos < 0) break;

          String hmacStr =
            credsJson.substring(hmacPos + 12, hmacPos + 76);

          int resPos =
            credsJson.indexOf("\"resource_code\":\"", p);

          char resCode = 'A';
          if (resPos >= 0) {
            resCode = credsJson.charAt(resPos + 17);
          }

          int statusPos = credsJson.indexOf("\"status\":\"", p);
          String statusStr = "active";

          if (statusPos >= 0) {
            int statusStart = statusPos + 10;
            int statusEnd = credsJson.indexOf('"', statusStart);

            if (statusEnd > statusStart) {
              statusStr =
                credsJson.substring(statusStart, statusEnd);
            }
          }

          bool found = false;

          for (int c = 0; c < localCredentialCount; c++) {
            if (localCredentials[c].id == nextId) {
              strlcpy(localCredentials[c].status,
                      statusStr.c_str(),
                      sizeof(localCredentials[c].status));

              strlcpy(localCredentials[c].pin_hmac,
                      hmacStr.c_str(),
                      sizeof(localCredentials[c].pin_hmac));

              found = true;
              break;
            }
          }

          if (!found) {
            CredentialRecord& cr =
              localCredentials[localCredentialCount++];

            cr.id = nextId;
            cr.resource_code = resCode;

            strlcpy(cr.status, statusStr.c_str(),
                    sizeof(cr.status));

            strlcpy(cr.pin_hmac, hmacStr.c_str(),
                    sizeof(cr.pin_hmac));
          }

          Serial.printf(
            "[STORE] Credential %d (%c) -> %s\n",
            nextId, resCode, statusStr.c_str()
          );

          p += 5;
        }
      }
    }

    eventQueueCount = 0;
    Serial.println("[SYNC] Telemetry event queue cleared.");

  } else {
    Serial.printf(
      "[SYNC] Request failed with HTTP %d: %s\n",
      httpCode, http.errorToString(httpCode).c_str()
    );
  }

  http.end();
}
// ============================================================================
// 10. CRYPTOGRAPHIC SELF-TEST VECTORS
// ============================================================================

void runSelfTestVectors() {
  Serial.println("\n--- RUNNING CRYPTOGRAPHIC TEST VECTORS ---");

  String tv1Msg = "A:482916";
  String tv1Key = "dkac-test-vector-key-0001";
  String tv1Expected =
    "e48f878502a47172ea00cf018627956dab95a5073357dc5b01220bc4179093bc";

  String tv1Calculated = hmacSha256Hex(tv1Key, tv1Msg);

  if (tv1Calculated == tv1Expected) {
    Serial.println("[PASS] PIN HMAC-SHA256 test vector");
  } else {
    Serial.println("[FAIL] PIN HMAC-SHA256 test vector");
    Serial.printf("Expected: %s\nGot:      %s\n",
                  tv1Expected.c_str(), tv1Calculated.c_str());
  }

  String tv2Key = "dkac-device-test-key-0001";
  String tv2Body =
    "{\"server_time\":\"2026-10-12T09:15:02Z\","
    "\"request_nonce\":\"c4b8e21a8f9042b7\"}";

  String tv2Expected =
    "c9c1a47b519b81ab2d9423dc9f6d57b379da7d2ef35326212ef9ccba6f972022";

  String tv2Calculated = hmacSha256Hex(tv2Key, tv2Body);

  if (tv2Calculated == tv2Expected) {
    Serial.println("[PASS] Response HMAC-SHA256 test vector");
  } else {
    Serial.println("[FAIL] Response HMAC-SHA256 test vector");
    Serial.printf("Expected: %s\nGot:      %s\n",
                  tv2Expected.c_str(), tv2Calculated.c_str());
  }

  Serial.println("-------------------------------------------\n");
}

// ============================================================================
// 11. SETUP
// ============================================================================

void setup() {
  Serial.begin(115200);
  delay(1000);

  setenv("TZ", "UTC0", 1);
  tzset();

  Serial.println("\n=======================================================");
  Serial.println("  Digital Key Access Control - ESP32 Access Terminal");
  Serial.println("=======================================================");


  pinMode(SERVO_PIN, OUTPUT);

  setupLCD();
  lockLatch();
  setupKeypad();
  showLCD("Digital Locker", "Connecting WiFi");

  Serial.println("[HARDWARE] Keypad, LCD and servo initialized.");

  runSelfTestVectors();

  backendBaseUrl =
    "https://digital-key-backend-2qvp.onrender.com";

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
    Serial.printf("\n[WIFI] Connected! IP: %s\n",
                  WiFi.localIP().toString().c_str());
    showLCD("WiFi connected", "Syncing...");

    // Initialize system time before HTTPS certificate validation.
    configTime(0, 0, "pool.ntp.org", "time.google.com");

    struct tm tlsTime;
    unsigned long ntpStart = millis();

    while (!getLocalTime(&tlsTime, 500) &&
           millis() - ntpStart < 10000) {
      Serial.println("[TIME] Waiting for NTP time before HTTPS...");
    }

    if (getLocalTime(&tlsTime, 100)) {
      Serial.println("[TIME] NTP initialized for HTTPS.");
    } else {
      Serial.println(
        "[TIME] NTP unavailable; HTTPS validation may fail."
      );
    }


    testHealthEndpoint();
    syncWithBackend();

  } else {
    Serial.println("\n[WIFI] Connection failed. Offline mode.");
    showLCD("WiFi unavailable", "Offline mode");

  }

  showLCD("Resource A", "Enter PIN: ");
  Serial.println("\n--- Interactive Terminal Ready ---");
  Serial.println(
    "Keypad: 6 digits + '#' submit, '*' clear, A/B switch resource."
  );
  Serial.println(
    "Serial: h=health, s=sync, l=servo, v=self-tests, k=status"
  );
}

// ============================================================================
// 12. MAIN LOOP
// ============================================================================

unsigned long lastSyncMillis = 0;
const unsigned long SYNC_INTERVAL_MS = 15000;

void loop() {
  // 1. Physical keypad
  char physicalKey = scanKeypad();

  if (physicalKey != 0) {
    Serial.printf("[KEYPAD] Pressed: '%c'\n", physicalKey);
    processKeyInput(physicalKey);
  }

  // 2. Serial command console
  if (Serial.available() > 0) {
    char ch = Serial.read();

    if (ch == 'h' || ch == 'H') {
      testHealthEndpoint();

    } else if (ch == 's' || ch == 'S') {
      syncWithBackend();

    } else if (ch == 'l' || ch == 'L') {
      Serial.println("[TEST] Manual servo test: 180 degrees, then return to 0.");

      unlockLatch();
      delay(2000);
      lockLatch();

    } else if (ch == 'v' || ch == 'V') {
      runSelfTestVectors();

    } else if (ch == 'k' || ch == 'K') {
      Serial.printf(
        "[STATUS] Resource: %c | Buffer: '%s' | Credentials: %d"
        " | Lockout: %s | Time: %s\n",
        selectedResource,
        pinBuffer,
        localCredentialCount,
        (millis() < lockoutUntilMillis) ? "ACTIVE" : "NONE",
        getDeviceTimestampIso().c_str()
      );

    } else if (
      (ch >= '0' && ch <= '9') ||
      ch == '*' || ch == '#' ||
      ch == 'A' || ch == 'B' ||
      ch == 'a' || ch == 'b'
    ) {
      char upper = toupper(ch);
      Serial.printf("[SERIAL INPUT] Key: '%c'\n", upper);
      processKeyInput(upper);
    }
  }

  // 3. Periodic sync heartbeat
  if (millis() - lastSyncMillis >= SYNC_INTERVAL_MS) {
    lastSyncMillis = millis();

    if (WiFi.status() == WL_CONNECTED) {
      syncWithBackend();
    }
  }

}
