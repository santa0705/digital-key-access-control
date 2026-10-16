# Digital Key Access Control — ESP32 Hardware Wiring & Test Notes

Authoritative specifications: `docs/api-contract.md §5.4` and `docs/credential-policy.md §5 & §6`.

---

## 1. GPIO Pinout & Hardware Connections

### 1.1 4x4 Matrix Keypad (8 pins total)
The firmware uses pure internal pull-ups on rows (`INPUT_PULLUP`) and actively strobes columns (`OUTPUT` LOW). No external pull-up resistors or third-party libraries required.

| Matrix Pin | ESP32 GPIO | Description | Safe Notes |
|---|---|---|---|
| **Row 1** | **GPIO 19** | Keypad Row 1 (`1, 2, 3, A`) | Internal pull-up |
| **Row 2** | **GPIO 18** | Keypad Row 2 (`4, 5, 6, B`) | Internal pull-up |
| **Row 3** | **GPIO 5**  | Keypad Row 3 (`7, 8, 9, C`) | Internal pull-up |
| **Row 4** | **GPIO 17** | Keypad Row 4 (`*, 0, #, D`) | Internal pull-up |
| **Col 1** | **GPIO 23** | Keypad Col 1 (`1, 4, 7, *`) | Output strobe |
| **Col 2** | **GPIO 22** | Keypad Col 2 (`2, 5, 8, 0`) | Output strobe |
| **Col 3** | **GPIO 21** | Keypad Col 3 (`3, 6, 9, #`) | Output strobe |
| **Col 4** | **GPIO 16** | Keypad Col 4 (`A, B, C, D`) | Output strobe |

### 1.2 Key Map & Functions
- **Digits `0`–`9`:** Accumulates up to 6 digits in the PIN buffer.
- **Key `A`:** Selects **Resource A** (physical locker, servo-actuated).
- **Key `B`:** Selects **Resource B** (simulated locker).
- **Key `*` (Clear):** Clears the current PIN buffer and resets indicators.
- **Key `#` (Enter):** Validates the 6-digit PIN against local active credentials.

### 1.3 SG90 Servo Actuator (Locker A physical latch)
| Servo Wire | Connection | Notes |
|---|---|---|
| **Signal (Orange/Yellow)** | **GPIO 13** | Safe PWM output pin; avoids bootstrapping pins 12 & 15. |
| **Power (Red)** | **External 5V supply** | **CRITICAL:** Do NOT power servo from ESP32 3.3V or VIN to prevent brownouts! |
| **Ground (Brown/Black)** | **Common Ground (GND)** | Must be tied together with ESP32 GND. |

- **Locked Position:** `0°` (pulse ~1000 µs)
- **Unlocked Position:** `90°` (pulse ~1750 µs, holds for 3 seconds then returns to 0°)

### 1.4 Status LEDs
| Component | ESP32 GPIO | Resistor | Description |
|---|---|---|---|
| **Green LED** | **GPIO 4** | 220 Ω to GND | Lights during valid access and servo unlock. |
| **Red LED** | **GPIO 2** | 220 Ω to GND | Onboard LED / external Red LED; flashes on wrong PIN; solid/blinking during 30s lockout. |

---

## 2. Interactive Serial Test Console (115200 Baud)

When testing via USB cable, the firmware provides single-character commands directly through the Arduino Serial Monitor:

| Command | Action |
|---|---|
| **`h`** | Run operational health probe (`GET http://10.202.183.98:8000/health`). |
| **`s`** | Trigger immediate sync (`POST /device/v1/sync`) with nonce & signature verification. |
| **`l`** | Test servo actuation (unlock 3 seconds $\rightarrow$ lock). |
| **`v`** | Run Cryptographic Test Vectors 1 & 2 self-test. |
| **`k`** | Display current buffer status, selected resource, and loaded credentials. |
| **`a` / `b`** | Simulate keypad resource selection (`A` or `B`). |
| **`0`–`9`** | Simulate entering a digit without physical keypad. |
| **`*`** | Simulate Clear button. |
| **`#`** | Simulate Enter button to validate current buffer. |

---

## 3. Immediate Hardware Verification Checklist

1. Open Arduino IDE (file `sketch_oct15b.ino` is already updated and compiled).
2. Select Port `COM5` (or active ESP32 port) and click **Upload**.
3. Open Serial Monitor at **115200 baud**.
4. Confirm Wi-Fi connection and health probe response:
   - Output shows `[WIFI] Connected!` and `[PROBE] HTTP Status: 200`.
5. Type `s` in Serial Monitor or wait 15 seconds:
   - Confirms `[SYNC] HTTP 200 OK` and `[SECURITY] X-Server-Signature VERIFIED successfully!`.
6. Press keys on the physical keypad to confirm matrix wiring:
   - Output prints `[PHYSICAL KEYPAD] Pressed: '<key>'`.
7. Enter valid approved PIN + `#`:
   - Green LED turns ON, servo swings 90°, holds 3 seconds, returns to locked position.
