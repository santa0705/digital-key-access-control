# Hardware Setup & Physical Assembly Guide

This document describes the complete physical assembly, electrical connections, wiring schema, power isolation, and hardware testing procedures for the **Digital Key Access Control** physical terminal.

---

## 1. Bill of Materials & Component Inventory

| Component | Specification | Quantity | Primary Function |
|---|---|---|---|
| **ESP32 Development Board** | ESP32-WROOM-32 / NodeMCU-32S (30 or 38 pins) | 1 | Terminal microcontroller, Wi-Fi HTTPS sync client, cryptographic engine, peripheral controller. |
| **Matrix Keypad** | 4Ã—4 Membrane or Tactile Keypad (16 keys: `0-9`, `*`, `#`, `A-D`) | 1 | User PIN entry, clear key (`*`), submission key (`#`), resource selector (`A`, `B`). |
| **IÂ²C Character LCD** | 16Ã—2 LCD with soldered PCF8574 IÂ²C backpack | 1 | Live system status, prompt display, countdown timers, access feedback messages. |
| **Micro-Servo Motor** | SG90 9g TowerPro (analog PWM servo) | 1 | Mechanical physical lock actuation (0Â° locked $\leftrightarrow$ 180Â° unlocked). |
| **External Power Supply** | 5V DC Regulated Power Supply (â‰¥ 1.5A) or dual-rail breadboard power supply | 1 | Dedicated clean power rail for the servo motor and LCD backlight to isolate motor inductive spikes. |
| **Breadboard & Wires** | Full-size solderless breadboard + male-to-male and male-to-female jumper wires | 1 set | Prototyping interconnections and shared ground bus. |

> [!NOTE]
> The final implemented terminal **does not use** discrete LEDs (no green or red LEDs), an external buzzer, or an RTC breakout board (DS1307/DS3231). All user signaling is handled cleanly via the 16Ã—2 IÂ²C LCD display, and timekeeping is maintained through NTP and backend signed time anchoring.

---

## 2. Complete Wiring Diagram & Pin Assignments

```
                 +-------------------------------------------------+
                 |              ESP32 DEV MODULE (30P)             |
                 |                                                 |
(Row 1) GPIO 19  |<---- Keypad Row 1 (Pin 1)                       |
(Row 2) GPIO 18  |<---- Keypad Row 2 (Pin 2)                       |
(Row 3) GPIO 5   |<---- Keypad Row 3 (Pin 3)                       |
(Row 4) GPIO 17  |<---- Keypad Row 4 (Pin 4)                       |
(Col 1) GPIO 23  |----> Keypad Col 1 (Pin 5)                       |
(Col 2) GPIO 22  |----> Keypad Col 2 (Pin 6)                       |
(Col 3) GPIO 21  |----> Keypad Col 3 (Pin 7)                       |
(Col 4) GPIO 16  |----> Keypad Col 4 (Pin 8)                       |
                 |                                                 |
        GPIO 26  |<---> I2C LCD SDA                                |
        GPIO 27  |----> I2C LCD SCL                                |
                 |                                                 |
        GPIO 13  |----> SG90 Servo PWM Signal                      |
                 |                                                 |
            GND  |<==== COMMON GROUND BUS =========================|==== (Servo GND & External 5V GND)
            VIN  |<---- (Optional 5V power from USB or external)  |
                 +-------------------------------------------------+
```

### 2.1 Complete Pinout Table

| ESP32 GPIO | Connected Component | Component Pin / Wire | Direction / Mode | Electrical Specification |
|---|---|---|---|---|
| **GPIO 19** | 4Ã—4 Matrix Keypad | Row 1 (Pin 1) | `INPUT_PULLUP` | Reads Keys `1, 2, 3, A`. Internal ~45kÎ© pull-up. |
| **GPIO 18** | 4Ã—4 Matrix Keypad | Row 2 (Pin 2) | `INPUT_PULLUP` | Reads Keys `4, 5, 6, B`. Internal ~45kÎ© pull-up. |
| **GPIO 5**  | 4Ã—4 Matrix Keypad | Row 3 (Pin 3) | `INPUT_PULLUP` | Reads Keys `7, 8, 9, C`. Internal ~45kÎ© pull-up. |
| **GPIO 17** | 4Ã—4 Matrix Keypad | Row 4 (Pin 4) | `INPUT_PULLUP` | Reads Keys `*, 0, #, D`. Internal ~45kÎ© pull-up. |
| **GPIO 23** | 4Ã—4 Matrix Keypad | Column 1 (Pin 5) | `OUTPUT` | Strobed LOW during scan cycle. |
| **GPIO 22** | 4Ã—4 Matrix Keypad | Column 2 (Pin 6) | `OUTPUT` | Strobed LOW during scan cycle. |
| **GPIO 21** | 4Ã—4 Matrix Keypad | Column 3 (Pin 7) | `OUTPUT` | Strobed LOW during scan cycle. |
| **GPIO 16** | 4Ã—4 Matrix Keypad | Column 4 (Pin 8) | `OUTPUT` | Strobed LOW during scan cycle. |
| **GPIO 26** | 16Ã—2 IÂ²C LCD | SDA (Data) | Open-drain / IÂ²C | Connected to PCF8574 SDA pin. Initialized at 100 kHz. |
| **GPIO 27** | 16Ã—2 IÂ²C LCD | SCL (Clock) | Open-drain / IÂ²C | Connected to PCF8574 SCL pin. Initialized at 100 kHz. |
| **GPIO 13** | SG90 Servo Latch | Orange / Yellow Lead | `OUTPUT` (PWM) | 50 Hz pulse stream (`500 Âµs` = 0Â°, `2500 Âµs` = 180Â°). |
| **GND**     | Breadboard Ground Rail | Common GND Bus | Power Ground | Must bridge ESP32 GND, Servo GND, and 5V Power Supply GND. |

---

## 3. Critical Power Isolation & Electrical Safety

> [!CAUTION]
> **Do not power the SG90 servo motor directly from the ESP32 3.3V or 5V VIN pin.**
> An SG90 servo draws up to 500mAâ€“800mA stall current when moving or overcoming latch mechanical friction. The on-board linear regulator (AMS1117-3.3) on typical ESP32 boards is rated for 800mA maximum and supplies the ESP32 core, Wi-Fi radio, and flash. If the servo draws peak current from this rail, the supply voltage drops below the ESP32 brownout threshold (~2.8V), causing immediate and continuous system reboot cycles.

### 3.1 Power Architecture Checklist
1. **Dedicated 5V Servo Rail:** Connect the red wire (+5V) and brown/black wire (GND) of the SG90 servo to a separate 5V power supply or an external breadboard power adapter.
2. **Mandatory Common Ground:** You **must** connect the ground (GND) of the external 5V power supply to the ground (GND) pin of the ESP32 board. Without a shared ground reference, the PWM control signal on GPIO 13 will float, resulting in erratic jitter, erratic rotation, or complete lack of response.
3. **IÂ²C Bus Voltage Compatibility:** The PCF8574 backpack typically operates at 5V. On the IÂ²C bus, open-drain pull-ups pull the lines toward the backpack voltage. While ESP32 GPIOs 26 and 27 are generally 5V tolerant on many development boards, for maximum long-term reliability, ensure pull-up resistors on SDA/SCL tie to 3.3V if using discrete external pull-up resistors.

---

## 4. Mechanical Latch Assembly & Calibration

1. **Mounting the Servo:** Secure the SG90 servo body firmly to the locker enclosure or test frame using the provided mounting screws or a rigid 3D-printed bracket.
2. **Zero-Point Calibration (0Â°):**
   - Connect the ESP32 and open the Serial Monitor (115200 baud).
   - Press `l` to actuate the servo test cycle. When the servo stops at the relaxed position, it is at **0Â° (Locked)**.
   - Attach the servo horn (single-arm or double-arm) such that the horn physically engages the door keeper in this position.
3. **Unlocked Sweep (180Â°):**
   - Upon successful PIN authentication, the firmware generates a 2500 Âµs pulse moving the horn to **180Â°**, retracting the latch keeper.
   - It maintains this position for 3.0 seconds (`delay(3000)`), giving the user sufficient time to pull open the physical door.
   - The horn automatically swings back to **0Â°** to re-engage the latch.

---

## 5. LCD Contrast & Troubleshooting

1. **Backlight On but Blank Display:**
   - The PCF8574 backpack features a small blue potentiometer on the rear.
   - Use a small flat-head screwdriver to slowly rotate the potentiometer until dark rectangular character blocks become sharp and legible against the backlight.
2. **IÂ²C Address Verification:**
   - Standard PCF8574 chips use address `0x27`.
   - PCF8574A variants use address `0x3F`.
   - The firmware initializes `DIYables_LCD_I2C lcd(0x27, 16, 2);`. If your display remains unresponsive despite correct contrast, verify your backpack IÂ²C address using an IÂ²C scanner sketch.
