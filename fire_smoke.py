"""
Fire/smoke detection, kept completely independent of the theft
detection state machine on purpose:

- It has no cooldown timer (a fire alert should NEVER be suppressed).
- It doesn't wait for person-detection confirmation (a fire matters
  whether or not a person is in frame).
- It runs continuously regardless of what state the theft machine is in.

IMPORTANT SAFETY NOTE: this is a supplementary detection layer for a
DIY/small-site build. It is not a substitute for certified fire
detection and suppression equipment required by local fire code at a
commercial EV charging site — battery fires in particular can escalate
very fast and may need specialized suppression (e.g. Class D or
lithium-specific extinguishing agents) that this system cannot provide.
"""

import threading
import time

import config

try:
    import RPi.GPIO as GPIO
    import spidev
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False


class FireSmokeMonitor:
    def __init__(self, sensor_hub, recorder, mqtt_client):
        self.sensor_hub = sensor_hub
        self.recorder = recorder
        self.mqtt_client = mqtt_client
        self._running = False
        self._smoke_samples = []

        if HARDWARE_AVAILABLE:
            GPIO.setup(config.FLAME_SENSOR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def start(self):
        if not config.FIRE_SMOKE_ENABLED:
            print("[fire_smoke] disabled in config, not starting")
            return
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()
        print("[fire_smoke] monitor started")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            if self._check_flame() or self._check_smoke():
                self._trigger_fire_alert()
                # after a fire alert, wait before re-checking so a single
                # ongoing event doesn't spam duplicate alerts — but note
                # there is no long cooldown like theft alerts, since a
                # worsening fire (e.g. spreading) still deserves re-alerts
                time.sleep(30)
            time.sleep(1.0 / config.FIRE_SAMPLE_HZ)

    def _check_flame(self):
        if not HARDWARE_AVAILABLE:
            return False  # dev-mode: no flame sensor to read
        # active-low IR flame sensors: LOW means flame detected
        return GPIO.input(config.FLAME_SENSOR_PIN) == GPIO.LOW

    def _read_smoke_raw(self):
        if not HARDWARE_AVAILABLE:
            return 0
        spi = spidev.SpiDev()
        spi.open(0, 0)
        spi.max_speed_hz = 1_000_000
        cmd = [1, (8 + config.MQ2_SMOKE_CHANNEL) << 4, 0]
        response = spi.xfer2(cmd)
        spi.close()
        return ((response[1] & 3) << 8) + response[2]

    def _check_smoke(self):
        raw = self._read_smoke_raw()
        self._smoke_samples.append(raw >= config.SMOKE_THRESHOLD_RAW)
        self._smoke_samples = self._smoke_samples[-config.FIRE_DEBOUNCE_SAMPLES:]
        return (
            len(self._smoke_samples) == config.FIRE_DEBOUNCE_SAMPLES
            and all(self._smoke_samples)
        )

    def _trigger_fire_alert(self):
        print("[fire_smoke] *** FIRE/SMOKE DETECTED — HIGH PRIORITY ***")

        # Protect current footage the same way a theft event does —
        # useful for insurance/investigation regardless of cause.
        self.recorder.lock_incident()

        self.sensor_hub.sound_buzzer(duration_seconds=config.FIRE_ALARM_BUZZER_PATTERN_SECONDS)

        self.mqtt_client.publish_alert(
            "fire_smoke_detected",
            extra={
                "high_priority": True,
                "topic_override": config.MQTT_TOPIC_FIRE_ALERT,
            },
        )
