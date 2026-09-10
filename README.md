# EV charger theft detection — single unit build

A Raspberry Pi based system that continuously records a rolling 15-minute
video buffer, detects unauthorized cable/plug removal or a sudden current
cut, locks the buffer, records 15 more minutes after the event, and
uploads the combined clip to the cloud.

## Hardware needed

| Part | Approx cost | Notes |
|---|---|---|
| Raspberry Pi Zero 2 W | $15 | Needs enough CPU for continuous H.264 encoding — a plain ESP32-CAM cannot do this |
| Raspberry Pi Camera Module 3 | $25 | Or any CSI camera supported by picamera2 |
| ACS712 current sensor (30A) | $3 | Clips onto the charging cable's live line |
| MCP3008 ADC chip | $3 | Pi has no analog input pins, this converts the ACS712's analog output to digital over SPI |
| Hall-effect / reed switch | $1 | Mounted in the connector holster |
| Piezo buzzer or 5V relay + siren | $2 | Audible deterrent on trigger |
| MicroSD card (32GB+) | $8 | Stores the rolling buffer |
| 4G/LTE USB dongle or existing WiFi | varies | For cloud upload |

**Total: roughly $60-70 in parts.**

## Wiring overview

- **ACS712 → MCP3008 → Pi**: ACS712 analog output goes to MCP3008 channel 0.
  MCP3008 talks to the Pi over SPI (CE0, MOSI, MISO, SCLK — enable SPI via
  `raspi-config` first).
- **Holster switch → GPIO 17**: one leg to GPIO 17, the other to GND.
  Internal pull-up is used in software, so no external resistor needed.
- **Buzzer/relay → GPIO 27**: through a transistor/relay if your buzzer
  draws more current than a GPIO pin can source directly.
- **Camera Module → CSI port** directly on the Pi.

## Software setup

```bash
# On the Raspberry Pi (Raspberry Pi OS Bookworm or later)
sudo apt update
sudo apt install -y python3-picamera2 ffmpeg
pip install -r requirements.txt --break-system-packages

# Enable SPI for the MCP3008
sudo raspi-config  # -> Interface Options -> SPI -> Enable
```

Edit `config.py` before running:
- `STORAGE_DIR` — where footage lives (make sure the SD card has room)
- `MQTT_BROKER`, `MQTT_*_CERT` — your broker address and TLS certs
- `UPLOAD_URL_REQUEST_ENDPOINT`, `DEVICE_API_KEY` — your backend for
  issuing pre-signed upload URLs
- `ACS712_ZERO_CURRENT_VOLTAGE` — **must be calibrated on your actual
  board** (see below), don't trust the default

## Calibrating the current sensor

The ACS712 outputs `Vref/2` (usually ~1.65V on a 3.3V system) when no
current is flowing. This varies slightly board to board. To calibrate:

1. With nothing plugged in, run a small script that just prints
   `sensors.read_current_amps()` repeatedly.
2. It should read close to 0A. If it's off by more than ~0.3A, adjust
   `ACS712_ZERO_CURRENT_VOLTAGE` in `config.py` up or down until it reads
   near zero at rest.
3. Once charging, confirm the reading roughly matches your charger's
   actual rated current (e.g. ~16A). If not, double check
   `ACS712_SENSITIVITY_MV_PER_A` matches your specific ACS712 variant
   (20A, 30A, and 5A versions have different sensitivities).

## Running it

```bash
python3 main.py
```

For a real deployment, run this as a systemd service so it restarts
automatically on crash or reboot:

```ini
# /etc/systemd/system/charger-theft-detection.service
[Unit]
Description=EV charger theft detection
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/ev_theft_detector/main.py
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now charger-theft-detection
```

## Testing without real hardware

Every module falls back to a dev-mode stub if the Raspberry Pi-specific
libraries (`picamera2`, `RPi.GPIO`, `spidev`) aren't installed — so you
can run and test the state machine logic on a laptop before deploying to
the actual Pi. This is how the logic was verified during development.

## What you'll likely need to tune after a real deployment

This is the part that always takes longer than expected — budget a
1-2 week calibration period at the actual site before trusting the
system unattended:

- `CURRENT_DROP_THRESHOLD_PCT` and `CURRENT_DEBOUNCE_SAMPLES` — tune
  against your charger's real noise floor.
- `AUTH_WINDOW_SECONDS` — how long after a legitimate tap someone
  realistically takes to unplug.
- `ARMED_CHECK_TIMEOUT_SECONDS` — avoid false alarms from people who
  linger near the charger without touching it.

## New: person detection, plate OCR, fire/smoke detection, and dashboard

### Person detection
Before a theft alert fires, `person_detection.py` checks the snapshot for
an actual human. It auto-picks a backend:
- If you drop a real `yolov8n.onnx` model file at `models/yolov8n.onnx`,
  it uses that (more accurate, needs `onnxruntime`).
- Otherwise it falls back to OpenCV's built-in HOG people detector — no
  download needed, works out of the box, less accurate on side/partial
  views.

A missed detection does **not** cancel the alert — it just gets logged
as low-confidence, since a missed theft is worse than an occasional
false "person not confirmed" flag.

To get a real YOLOv8n ONNX model: `pip install ultralytics` then
`yolo export model=yolov8n.pt format=onnx` on a machine with more
horsepower than a Pi Zero 2 W, then copy the resulting `.onnx` file over.

### License plate capture
`plate_ocr.py` looks for plate-shaped rectangular regions in post-event
frames and runs Tesseract OCR on them. Needs `apt install tesseract-ocr`
on the Pi in addition to the `pytesseract` pip package. This is a
classic (non-deep-learning) approach — good enough as a first pass, but
if you find it unreliable in practice, swapping in a proper ALPR model
behind the same `read_plate()` function is a drop-in upgrade.

### Dashboard
`dashboard/app.py` is a small Flask app that lists incidents with
thumbnails. Run it as a **separate process** from `main.py`:

```bash
python3 dashboard/app.py
```

Then visit `http://<pi-ip>:5000` from your phone or laptop on the same
network. It reads from the same `incidents.json` file that the state
machine writes to, so no extra wiring needed between them.

### Fire / smoke detection
`fire_smoke.py` runs as its own independent monitor — it does **not**
share the theft detection's cooldown timer or state machine, since a
fire alert should never be suppressed by unrelated logic. It needs:
- An **MQ-2 gas/smoke sensor** wired to another MCP3008 ADC channel
  (channel 1 by default)
- An **IR flame sensor** (digital, active-low) wired to GPIO 23

**Calibrate `SMOKE_THRESHOLD_RAW` in `config.py` on-site** — MQ-2
sensors need a burn-in period (a few hours powered on) before readings
stabilize, and ambient baseline varies by location (a covered parking
structure vs. open air will read differently).

**Important safety note**: this is a supplementary layer for a DIY or
small-site build. It is not a substitute for certified fire detection
and suppression equipment required by local fire code at a commercial
charging site — battery fires can escalate very fast and may need
suppression this system cannot provide.

## File overview

- `config.py` — all tunable settings in one place
- `recorder.py` — rolling buffer, segment recording, lock/unlock logic
- `sensors.py` — current sensor, holster switch, buzzer, auth tracking
- `mqtt_client.py` — receives auth events, publishes alerts (theft and fire, separate topics)
- `upload.py` — clip assembly (ffmpeg concat), snapshot capture, cloud upload with retry
- `person_detection.py` — confirms a human is present before alerting
- `plate_ocr.py` — finds and reads license plates in post-event frames
- `fire_smoke.py` — independent fire/smoke monitor, own alert path
- `incidents_store.py` — simple JSON incident log shared with the dashboard
- `dashboard/app.py` — Flask web dashboard for viewing incidents
- `state_machine.py` — the core theft-detection logic tying everything together
- `main.py` — entry point, wires everything up and runs the system
