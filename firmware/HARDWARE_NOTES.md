# Digital Key Access Control — ESP32 Hardware Wiring & Hardware Notes

Authoritative specifications: `docs/api-contract.md §5.4` and `docs/credential-policy.md §5 & §6`.

---

## 1. Verified Hardware Pinout & Physical Connections

### 1.1 4×4 Matrix Keypad (8 Pins Total)
The firmware scans the keypad rows using internal pull-ups (`INPUT_PULLUP`) and actively strobes columns low (`OUTPUT` LOW). No external pull-up resistors or third-party keypad libraries are required.

| Matrix Pin | ESP32 GPIO | Electrical Mode | Safe Hardware Notes |
|---|---|---|---|
| **Row 1** | **GPIO 19** | `INPUT_PULLUP` | Keypad Row 1 (`1, 2, 3, A`) |
| **Row 2** | **GPIO 18** | `INPUT_PULLUP` | Keypad Row 2 (`4, 5, 6, B`) |
| **Row 3** | **GPIO 5**  | `INPUT_PULLUP` | Keypad Row 3 (`7, 8, 9, C`) |
| **Row 4** | **GPIO 17** | `INPUT_PULLUP` | Keypad Row 4 (`*, 0, #, D`) |
| **Col 1** | **GPIO 23** | `OUTPUT` (Strobe LOW) | Keypad Col 1 (`1, 4, 7, *`) |
| **Col 2** | **GPIO 22** | `OUTPUT` (Strobe LOW) | Keypad Col 2 (`2, 5, 8, 0`) |
| **Col 3** | **GPIO 21** | `OUTPUT` (Strobe LOW) | Keypad Col 3 (`3, 6, 9, #`) |
| **Col 4** | **GPIO 16** | `OUTPUT` (Strobe LOW) | Keypad Col 4 (`A, B, C, D`) |

### 1.2 16×2 I²C Character LCD (PCF8574 Backpack)
User feedback and system state are rendered in real time using the **DIYables LCD I2C** library.

| LCD Pin | ESP32 Connection | Electrical Notes |
|---|---|---|
| **GND** | **Common GND** | Tied to ESP32 ground rail. |
| **VCC** | **5V Power Rail** | Powered from external 5V regulated supply (or ESP32 5V/VIN pin when powered via USB). |
| **SDA** | **GPIO 26** | I²C Serial Data line initialized via `Wire.begin(26, 27)`. |
| **SCL** | **GPIO 27** | I²C Serial Clock line initialized via `Wire.begin(26, 27)`. |

- **Library:** `DIYables_LCD_I2C` (`#include <DIYables_LCD_I2C.h>`)
- **Constructor:** `DIYables_LCD_I2C lcd(0x27, 16, 2);`
- **I²C Address:** `0x27` (standard PCF8574 address; contrast potentiometer adjusted on backpack).

### 1.3 SG90 Micro-Servo Actuator (Physical Locker Latch)
The physical latch mechanism is driven by an SG90 servo using bit-banged 50 Hz PWM pulses (`500 µs` to `2500 µs`).

| Servo Lead | Connection | Critical Electrical Rules |
|---|---|---|
| **Signal (Orange/Yellow)** | **GPIO 13** | Safe PWM output pin; avoids strapping pins (GPIO 0, 2, 12, 15). |
| **Power (Red)** | **External 5V supply** | **CRITICAL:** Do NOT power servo directly from ESP32 3.3V rail. Voltage sag during motor stall causes ESP32 brownout reset. |
| **Ground (Brown/Black)** | **Common Ground (GND)** | Must be tied together with ESP32 ground for common signal reference. |

- **Locked Position:** `0°` (~500 µs pulse width)
- **Unlocked Position:** `180°` (~2500 µs pulse width)
- **Actuation Profile:** On access grant, servo sweeps to 180°, holds for 3.0 seconds (`delay(3000)`), and returns to 0° to relock.

### 1.4 Unused / Non-Implemented Peripherals
The final confirmed physical implementation **does not use**:
- Discrete LEDs (no green LED on GPIO 4, no red LED on GPIO 2)
- Buzzer / Audio piezo
- DS1307 / DS3231 RTC modules (time synchronization is performed securely via NTP + backend HTTPS response time-anchoring)

---

## 2. Keypad Input State Machine & Functions

- **Digits `0`–`9`:** Appends up to 6 numeric digits to the PIN buffer.
- **Key `A`:** Selects **Resource A** (Physical locker latch controlled by servo).
- **Key `B`:** Selects **Resource B** (Secondary / simulated shared resource).
- **Key `*` (Clear):** Clears the entered PIN buffer immediately and resets the LCD prompt.
- **Key `#` (Enter):** Validates the 6-digit buffer against active credentials in terminal RAM:
  - Formats HMAC canonical string: `<selectedResource>:<pin>` (e.g. `A:123456`).
  - Computes HMAC-SHA256 using `PIN_HMAC_KEY`.
  - Compares digest in constant time against cached active credentials.
  - On match: Latch unlocks for 3 seconds; event queued.
  - On mismatch: Increments failed attempt counter; triggers 30-second lockout after 3 consecutive failures.

---

## 3. LCD User Interface States

| System State | LCD Line 1 (16 chars) | LCD Line 2 (16 chars) |
|---|---|---|
| **Boot / Init** | `Digital Locker` | `Starting...` |
| **Wi-Fi Connect** | `Digital Locker` | `Connecting WiFi` |
| **Wi-Fi Connected** | `WiFi connected` | `Syncing...` |
| **Idle / Ready** | `Resource: A` | `Enter PIN: ______` |
| **Key Pressed** | `Resource: A` | `Enter PIN: ***` |
| **Access Granted** | `ACCESS GRANTED` | `Unlocking...` |
| **Wrong PIN** | `ACCESS DENIED` | `Invalid PIN` |
| **Credential Used** | `PIN REJECTED` | `Already used` |
| **Credential Revoked** | `PIN REJECTED` | `Revoked PIN` |
| **Terminal Lockout** | `ACCESS LOCKED` | `<remaining> sec remaining` |

---

## 4. Interactive Serial Test Console (115200 Baud)

When tethered via USB cable, the firmware provides single-character debugging commands directly through the Arduino Serial Monitor:

| Command | Action | Description |
|---|---|---|
| **`h`** | Health Probe | Executes operational check (`GET /health`) and synchronizes clock. |
| **`s`** | Trigger Sync | Triggers immediate sync (`POST /device/v1/sync`) with signed response verification. |
| **`l`** | Latch Test | Manually actuates servo: sweeps to 180°, delays 2s, returns to 0°. |
| **`v`** | Self-Test Vectors | Verifies Cryptographic Test Vectors 1 (HMAC) & 2 (Signature). |
| **`k`** | Status Dump | Displays resource selection, buffer length, credential count, lockout timer, and ISO timestamp. |
| **`a` / `b`** | Resource Switch | Simulates keypad `A` or `B` selection. |
| **`0`–`9`** | PIN Entry | Simulates entering a numeric digit. |
| **`*`** | Clear Key | Simulates pressing the keypad `*` button. |
| **`#`** | Enter Key | Simulates pressing `#` to submit PIN for verification. |

---

## 5. Hardware Setup & Verification Checklist

1. **Verify Wiring:** Check row/column keypad connections, servo signal to GPIO 13, and LCD SDA to GPIO 26 / SCL to GPIO 27.
2. **Power Requirements:** Connect external 5V power supply to SG90 servo VCC/GND with common ground tied to ESP32 GND.
3. **Configure Secrets:** Copy `firmware/secrets.h.example` to `firmware/secrets.h` and provide your Wi-Fi SSID, Wi-Fi password, `DEVICE_API_KEY`, and `PIN_HMAC_KEY`.
4. **Compile & Upload:**
   - Arduino IDE → Select **ESP32 Dev Module**.
   - Board Settings: Flash Frequency 80MHz, Upload Speed 921600, Partition Scheme Default 4MB with spiffs.
   - Install library: **DIYables_LCD_I2C** via Arduino Library Manager.
   - Open `firmware/esp32_sync_terminal.ino` and upload.
5. **Monitor Serial:** Open Serial Monitor at **115200 baud**:
   - Confirm Cryptographic Test Vectors 1 & 2 pass: `[CRYPTO] Self-test Vector 1 PASS`.
   - Confirm Wi-Fi connects and NTP acquires network time.
   - Confirm initial sync completes: `[SYNC] HTTP 200 OK` and `[SECURITY] X-Server-Signature VERIFIED`.
6. **Physical Test:**
   - Enter active PIN on keypad followed by `#`.
   - Confirm LCD displays `ACCESS GRANTED`, servo sweeps to 180°, holds 3 seconds, and returns to 0°.
