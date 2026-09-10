"""
Reads the physical sensors and tracks recent authorization events.

Hardware assumed:
- Holster switch: Hall-effect/reed switch on a GPIO pin, active-low when docked.
- Current sensor: ACS712 analog output read through an MCP3008 ADC over SPI
  (Raspberry Pi has no built-in analog input).
- Auth events arrive over MQTT from your app/RFID backend (see mqtt_client.py)
  and are recorded here with a timestamp.
"""

import collections
import time

import config

try:
    import RPi.GPIO as GPIO
    import spidev
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False


class SensorHub:
    def __init__(self):
        self._last_auth_time = 0.0
        self._current_samples = collections.deque(maxlen=config.CURRENT_DEBOUNCE_SAMPLES)
        self._baseline_current = None  # set once charging starts, for anomaly comparison

        if HARDWARE_AVAILABLE:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(config.HOLSTER_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(config.BUZZER_PIN, GPIO.OUT, initial=GPIO.LOW)
            GPIO.setup(config.AUTH_BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

            self._spi = spidev.SpiDev()
            self._spi.open(0, 0)
            self._spi.max_speed_hz = 1_000_000
        else:
            self._spi = None

    # ---------- auth tracking ----------

    def record_auth_event(self):
        """Call this when an RFID tap / app session-start message arrives."""
        self._last_auth_time = time.time()
        print("[sensors] auth event recorded")

    def is_auth_recent(self, window_seconds=None):
        window = window_seconds or config.AUTH_WINDOW_SECONDS
        return (time.time() - self._last_auth_time) <= window

    # ---------- holster switch ----------

    def is_plug_docked(self):
        if not HARDWARE_AVAILABLE:
            return True  # dev-mode default: assume docked/idle
        # active-low: pin reads LOW when magnet is present (docked)
        return GPIO.input(config.HOLSTER_PIN) == GPIO.LOW

    # ---------- current sensor ----------

    def _read_adc_raw(self, channel):
        if not HARDWARE_AVAILABLE:
            return 512  # dev-mode stub: mid-scale value
        cmd = [1, (8 + channel) << 4, 0]
        response = self._spi.xfer2(cmd)
        return ((response[1] & 3) << 8) + response[2]

    def read_current_amps(self):
        raw = self._read_adc_raw(config.MCP3008_CURRENT_CHANNEL)
        voltage = (raw / 1023.0) * config.ADC_VREF
        amps = (voltage - config.ACS712_ZERO_CURRENT_VOLTAGE) / (
            config.ACS712_SENSITIVITY_MV_PER_A / 1000.0
        )
        return abs(amps)

    def set_baseline_current(self):
        """Call this once a legitimate charging session is confirmed active."""
        self._baseline_current = self.read_current_amps()
        print(f"[sensors] baseline current set to {self._baseline_current:.2f} A")

    def check_current_anomaly(self):
        """
        Returns True if current has dropped sharply below baseline for
        several consecutive samples (debounced), suggesting a cut cable
        rather than sensor noise.
        """
        if self._baseline_current is None or self._baseline_current < 0.5:
            return False  # no session active, nothing to compare against

        current = self.read_current_amps()
        drop_pct = (1 - (current / self._baseline_current)) * 100
        self._current_samples.append(drop_pct >= config.CURRENT_DROP_THRESHOLD_PCT)

        return (
            len(self._current_samples) == config.CURRENT_DEBOUNCE_SAMPLES
            and all(self._current_samples)
        )

    # ---------- buzzer ----------

    def sound_buzzer(self, duration_seconds=5):
        if not HARDWARE_AVAILABLE:
            print("[sensors] (dev-mode) buzzer would sound now")
            return
        GPIO.output(config.BUZZER_PIN, GPIO.HIGH)
        time.sleep(duration_seconds)
        GPIO.output(config.BUZZER_PIN, GPIO.LOW)

    def cleanup(self):
        if HARDWARE_AVAILABLE:
            GPIO.cleanup()
