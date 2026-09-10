"""
Central configuration for the EV charger theft detection system.
Tune these values to match your actual hardware and site conditions.
"""

import os

# --- Storage / buffer settings ---
STORAGE_DIR = "/home/pi/charger_footage"        # where video segments live
SEGMENT_SECONDS = 60                            # length of each recorded chunk
BUFFER_MINUTES = 15                             # how much "before" footage to keep
POST_EVENT_MINUTES = 15                         # how much "after" footage to record
VIDEO_RESOLUTION = (854, 480)                   # 480p is enough for identification
VIDEO_BITRATE = 1_000_000                       # ~1 Mbps, keeps files small


def state_file_path():
    """Computed dynamically so tests can override STORAGE_DIR at runtime."""
    return os.path.join(STORAGE_DIR, "buffer_state.json")

# --- GPIO pins (BCM numbering) ---
HOLSTER_PIN = 17          # Hall-effect / reed switch in connector holster
BUZZER_PIN = 27           # Piezo buzzer / relay to siren
AUTH_BUTTON_PIN = 22      # Optional physical "test auth" button, for bench testing

# --- Current sensor (via MCP3008 ADC over SPI) ---
MCP3008_CURRENT_CHANNEL = 0
ADC_VREF = 3.3
ACS712_SENSITIVITY_MV_PER_A = 66      # 66 mV/A for the 30A variant; check your chip
ACS712_ZERO_CURRENT_VOLTAGE = 1.65    # Vref/2, calibrate this on your actual board
CURRENT_DROP_THRESHOLD_PCT = 80       # % drop from baseline that counts as anomaly
CURRENT_SAMPLE_HZ = 50                # samples per second
CURRENT_DEBOUNCE_SAMPLES = 3          # consecutive anomalous samples required

# --- Auth / session window ---
AUTH_WINDOW_SECONDS = 30              # how long an auth tap "counts" as covering an unplug
ARMED_CHECK_TIMEOUT_SECONDS = 20      # how long to wait after motion before giving up

# --- MQTT ---
MQTT_BROKER = "your-broker-host"       # e.g. an EMQX/Mosquitto instance or AWS IoT endpoint
MQTT_PORT = 8883
MQTT_USE_TLS = True
MQTT_CLIENT_ID = "charger-station-01"
MQTT_TOPIC_ALERT = "chargers/station-01/alert"
MQTT_TOPIC_AUTH = "chargers/station-01/auth"     # your app/RFID backend publishes here
MQTT_CA_CERT = "/home/pi/certs/ca.pem"
MQTT_CLIENT_CERT = "/home/pi/certs/client.pem"
MQTT_CLIENT_KEY = "/home/pi/certs/client.key"

# --- Cloud upload ---
# Your backend should generate a short-lived pre-signed PUT URL per clip,
# rather than embedding long-lived storage credentials on the device.
UPLOAD_URL_REQUEST_ENDPOINT = "https://your-backend.example.com/api/upload-url"
DEVICE_API_KEY = "REPLACE_ME"           # used only to request the pre-signed URL

# --- Person detection (confirms a human is present before alerting) ---
PERSON_DETECTION_ENABLED = True
YOLO_ONNX_MODEL_PATH = "models/yolov8n.onnx"   # optional: drop a real model here for better accuracy
PERSON_DETECTION_MIN_CONFIDENCE = 0.5
# If no person is found in the snapshot, the alert is still sent but
# flagged low-confidence rather than silently dropped — camera angle or
# a partially-obscured person can still miss detection, and a missed
# theft alert is worse than an occasional low-confidence one.

# --- License plate capture ---
PLATE_OCR_ENABLED = True
PLATE_OCR_FRAME_COUNT = 5              # how many post-event frames to attempt OCR on

# --- Fire / smoke detection (independent of theft detection) ---
FIRE_SMOKE_ENABLED = True
MQ2_SMOKE_CHANNEL = 1                   # MCP3008 ADC channel for MQ-2 gas/smoke sensor
FLAME_SENSOR_PIN = 23                   # digital IR flame sensor, active-low on detection
SMOKE_THRESHOLD_RAW = 400               # ADC raw value above which smoke is considered present
                                         # MUST be calibrated on-site — see README
FIRE_DEBOUNCE_SAMPLES = 3               # consecutive anomalous samples required
FIRE_SAMPLE_HZ = 2
FIRE_ALARM_BUZZER_PATTERN_SECONDS = 15  # fire alarms should be louder/longer than theft buzzer
MQTT_TOPIC_FIRE_ALERT = "chargers/station-01/fire_alert"

# IMPORTANT: this camera/sensor-based system is a supplementary layer,
# not a replacement for certified fire detection/suppression equipment
# required by local fire code at a commercial charging site.

# --- Dashboard ---
DASHBOARD_HOST = "0.0.0.0"
DASHBOARD_PORT = 5000


def incidents_db_path():
    """Computed dynamically so tests can override STORAGE_DIR at runtime."""
    return os.path.join(STORAGE_DIR, "incidents.json")

# --- Misc ---
DEVICE_ID = "station-01"
ALERT_COOLDOWN_SECONDS = 60             # avoid re-alerting immediately after one fires
